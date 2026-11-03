"""Upload caps for trail files (brief §5 and §12, ADR-011 Amendment 1, D173): read a multipart upload in bounded memory.

The request cap (MAX_UPLOAD_REQUEST_MB) is checked against Content-Length before a byte is read, and again by counting
the body bytes as they arrive (chunked requests carry no Content-Length): the read stops at the first byte above it.
The file-count cap (MAX_UPLOAD_FILES) stops the read when the part one above it starts. Parts are kept in memory,
never spooled to the temporary folder (in the container /tmp is a 64 MB tmpfs), and each file keeps at most one byte
more than the per-file cap (MAX_UPLOAD_FILE_MB): enough for the import service to refuse it by name, never more.
MB = MiB.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.requests import Request

from overland_planner.application.catalog.facade import MIB, TrackFile

FILES_FIELD = "files"
_DEFAULT_FILE_NAME = "upload.gpx"


class UploadTooLargeError(Exception):
    """The request is above the request-size or file-count cap (413 `upload_too_large`)."""


class UploadFormError(Exception):
    """The request is not a multipart form with at least one file in `files` (422 `validation_error`)."""


@dataclass(frozen=True)
class UploadLimits:
    file_mb: int
    request_mb: int
    files: int

    @property
    def file_bytes(self) -> int:
        return self.file_mb * MIB

    @property
    def request_bytes(self) -> int:
        return self.request_mb * MIB

    def request_too_large(self) -> UploadTooLargeError:
        return UploadTooLargeError(f"The upload is larger than the {self.request_mb} MB limit")

    def too_many_files(self) -> UploadTooLargeError:
        return UploadTooLargeError(f"An upload can hold at most {self.files} files")


@dataclass
class _Part:
    field_name: str = ""
    file_name: str | None = None
    content: bytearray = field(default_factory=bytearray)


class _TrackFileCollector:
    """python-multipart callbacks: keeps each `files` part in memory, bounded by the caps."""

    def __init__(self, limits: UploadLimits) -> None:
        self._limits = limits
        self._keep = limits.file_bytes + 1
        self._part = _Part()
        self._header_name = b""
        self._header_value = b""
        self._disposition = b""
        self._file_count = 0
        self.files: list[TrackFile] = []

    def callbacks(self) -> dict[str, object]:
        return {
            "on_part_begin": self._on_part_begin,
            "on_header_field": self._on_header_field,
            "on_header_value": self._on_header_value,
            "on_header_end": self._on_header_end,
            "on_headers_finished": self._on_headers_finished,
            "on_part_data": self._on_part_data,
            "on_part_end": self._on_part_end,
        }

    def _on_part_begin(self) -> None:
        self._part = _Part()
        self._disposition = b""

    def _on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def _on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def _on_header_end(self) -> None:
        if self._header_name.lower() == b"content-disposition":
            self._disposition = self._header_value
        self._header_name = b""
        self._header_value = b""

    def _on_headers_finished(self) -> None:
        _, options = parse_options_header(self._disposition)
        self._part.field_name = options.get(b"name", b"").decode("utf-8", "replace")
        if b"filename" not in options or self._part.field_name != FILES_FIELD:
            return
        self._file_count += 1
        if self._file_count > self._limits.files:
            raise self._limits.too_many_files()
        self._part.file_name = options[b"filename"].decode("utf-8", "replace") or _DEFAULT_FILE_NAME

    def _on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._part.file_name is None:
            return  # other form fields are not read (their bytes still count against the request cap)
        room = self._keep - len(self._part.content)
        self._part.content += data[start : min(end, start + room)]

    def _on_part_end(self) -> None:
        if self._part.file_name is not None:
            self.files.append(TrackFile(self._part.file_name, bytes(self._part.content)))


async def read_track_files(request: Request, limits: UploadLimits) -> list[TrackFile]:
    """The files of a multipart upload. Raises `UploadTooLargeError` or `UploadFormError`."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limits.request_bytes:
        raise limits.request_too_large()
    content_type, params = parse_options_header(request.headers.get("content-type", ""))
    if content_type != b"multipart/form-data" or not params.get(b"boundary"):
        raise UploadFormError("Invalid request - files: the upload must be a multipart form")
    collector = _TrackFileCollector(limits)
    parser = MultipartParser(params[b"boundary"], collector.callbacks())  # type: ignore[arg-type]
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > limits.request_bytes:
                raise limits.request_too_large()
            parser.write(chunk)
        parser.finalize()
    except FormParserError:
        raise UploadFormError("Invalid request - files: the upload is not a valid multipart form") from None
    if not collector.files:
        raise UploadFormError("Invalid request - files: Field required")
    return collector.files
