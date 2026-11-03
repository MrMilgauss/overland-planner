"""Upload caps wired by the composition root (brief §5 and §12, ADR-011 Amendment 1, D173): 413 `upload_too_large`.

Integration level: single examples verify wiring through the real `create_app` with small caps (1 MB file, 2 MB
request, 2 files). The request cap holds before the body is read (Content-Length) and while it streams (chunked, no
Content-Length); nothing is spooled to the temporary folder; a refused upload adds no item and leaves no file in the
data folder. The per-file refusal property lives in tests/unit/application/catalog/test_track_import_service.py.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from overland_planner.bootstrap.app_factory import create_app
from overland_planner.bootstrap.startup import StartupRefusedError
from tests.common.workspace import workspace_data_dir

MIB = 1024 * 1024
CAPS = {"MAX_UPLOAD_FILE_MB": "1", "MAX_UPLOAD_REQUEST_MB": "2", "MAX_UPLOAD_FILES": "2"}
GPX = (
    b'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">'
    b'<trk><name>Assietta</name><trkseg><trkpt lat="45.056" lon="7.041"/><trkpt lat="44.958" lon="6.879"/>'
    b"</trkseg></trk></gpx>"
)


@pytest.fixture
def data_dir() -> Iterator[Path]:
    """A workspace data folder, never the OS temp folder (ADR-011 D121)."""
    with workspace_data_dir("integration") as folder:
        yield folder


@pytest.fixture
def spool_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every temporary file opened while the test runs (the container's /tmp is a 64 MB tmpfs, D173). A spooled
    upload rolls over into `tempfile.TemporaryFile`, which is unlinked at once, so the opening itself is recorded."""
    folder = tmp_path / "spool"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    opened: list[str] = []
    real = tempfile.TemporaryFile

    def recording(*args: Any, **kwargs: Any) -> Any:
        opened.append("TemporaryFile")
        return real(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryFile", recording)
    opened.extend(str(p) for p in folder.iterdir())
    return opened


@pytest.fixture
def planner(data_dir: Path) -> Iterator[tuple[FastAPI, TestClient, str]]:
    app = create_app({"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "mock", **CAPS})
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"name": "Alpi Occidentali giugno 2027"}).json()["id"]
        yield app, client, project_id


def stored(data_dir: Path) -> list[str]:
    return sorted(str(p.relative_to(data_dir)) for p in data_dir.rglob("*") if p.is_file() and "files" in p.parts)


def observed(client: TestClient, project_id: str, data_dir: Path) -> dict[str, Any]:
    project = client.get(f"/api/projects/{project_id}").json()
    items = client.get(f"/api/projects/{project_id}/items").json()
    return {"items": items, "revision": project["revision"], "stored": stored(data_dir)}


def test_a_declared_request_above_the_cap_is_refused_before_the_body_is_read(
    planner: tuple[FastAPI, TestClient, str], data_dir: Path
) -> None:
    app, client, project_id = planner
    before = observed(client, project_id, data_dir)
    reads: list[int] = []
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        reads.append(1)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": f"/api/projects/{project_id}/tracks",
        "raw_path": f"/api/projects/{project_id}/tracks".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"planner"),
            (b"content-type", b"multipart/form-data; boundary=x"),
            (b"content-length", str(2 * MIB + 1).encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("planner", 80),
    }
    asyncio.run(app(scope, receive, send))

    start, body = sent[0], b"".join(m.get("body", b"") for m in sent[1:])
    assert (start["status"], json.loads(body)) == (
        413,
        {"code": "upload_too_large", "message": "The upload is larger than the 2 MB limit"},
    )
    assert reads == []
    assert observed(client, project_id, data_dir) == before


def test_a_chunked_request_above_the_cap_is_refused_while_streaming_and_nothing_is_spooled(
    planner: tuple[FastAPI, TestClient, str], data_dir: Path, spool_dir: list[str]
) -> None:
    _, client, project_id = planner
    before = observed(client, project_id, data_dir)
    boundary = "planner-boundary"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="a.gpx"\r\n'
        "Content-Type: application/gpx+xml\r\n\r\n"
    ).encode()

    def body() -> Iterator[bytes]:  # no Content-Length: httpx sends it chunked
        yield head
        for _ in range(2 * 4 + 1):  # 9 x 256 KiB > 2 MB
            yield b"x" * (MIB // 4)
        yield f"\r\n--{boundary}--\r\n".encode()

    answer = client.post(
        f"/api/projects/{project_id}/tracks",
        content=body(),
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )

    assert "content-length" not in answer.request.headers
    assert (answer.status_code, answer.json()) == (
        413,
        {"code": "upload_too_large", "message": "The upload is larger than the 2 MB limit"},
    )
    assert spool_dir == []
    assert observed(client, project_id, data_dir) == before


def test_more_files_than_the_cap_are_refused_and_nothing_is_added(
    planner: tuple[FastAPI, TestClient, str], data_dir: Path
) -> None:
    _, client, project_id = planner
    before = observed(client, project_id, data_dir)

    answer = client.post(
        f"/api/projects/{project_id}/tracks",
        files=[("files", (f"t{n}.gpx", GPX, "application/gpx+xml")) for n in range(3)],
    )

    assert (answer.status_code, answer.json()) == (
        413,
        {"code": "upload_too_large", "message": "An upload can hold at most 2 files"},
    )
    assert observed(client, project_id, data_dir) == before


def test_a_file_above_its_cap_is_refused_by_name_and_leaves_no_file_while_one_at_the_cap_imports(
    planner: tuple[FastAPI, TestClient, str], data_dir: Path, spool_dir: list[str]
) -> None:
    _, client, project_id = planner
    before = observed(client, project_id, data_dir)

    refused = client.post(
        f"/api/projects/{project_id}/tracks",
        files=[
            ("files", ("assietta.gpx", GPX, "application/gpx+xml")),
            ("files", ("huge.gpx", GPX + b" " * MIB, "application/gpx+xml")),
        ],
    )

    assert (refused.status_code, refused.json()) == (
        413,
        {"code": "upload_too_large", "message": "huge.gpx is larger than the 1 MB limit"},
    )
    assert observed(client, project_id, data_dir) == before
    assert spool_dir == []

    accepted = client.post(
        f"/api/projects/{project_id}/tracks",
        files=[("files", ("edge.gpx", GPX + b" " * (MIB - len(GPX)), "application/gpx+xml"))],
    )
    assert accepted.status_code == 201, accepted.text
    assert [item["name"] for item in accepted.json()] == ["Assietta"]


@pytest.mark.parametrize("cap", ["MAX_UPLOAD_FILE_MB", "MAX_UPLOAD_REQUEST_MB", "MAX_UPLOAD_FILES"])
def test_a_non_positive_upload_cap_refuses_the_start(
    cap: str, data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(StartupRefusedError):
        create_app({"DATA_DIR": str(data_dir), **CAPS, cap: "0"})

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(line["event"], line["component"]) for line in lines] == [("health.startup.refused", "settings")]
    assert cap in lines[0]["reason"]
