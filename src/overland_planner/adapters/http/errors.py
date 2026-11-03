"""The /api error envelope (brief §5, D130, D183): every non-2xx answer under /api is {"code", "message"}.

Codes are enumerated per status; FastAPI's request validation body becomes `validation_error`; unknown /api paths
(and methods) and unknown ids answer 404 `not_found`. Paths outside /api (/healthz, the web page) keep their bodies.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException

from overland_planner.adapters.http.upload_limits import UploadFormError, UploadTooLargeError
from overland_planner.application.catalog.facade import ItemNotFoundError, ProjectNotFoundError, TrackFilesRefusedError
from overland_planner.domain.catalog.anchors import AnchorNotAPlaceError
from overland_planner.domain.catalog.coordinate import CoordinateOutOfRangeError
from overland_planner.domain.catalog.poi import PoiNameRequiredError
from overland_planner.domain.catalog.project import ProjectNameRequiredError

_CODE_BY_STATUS = {401: "unauthorized", 404: "not_found", 413: "upload_too_large", 422: "validation_error"}
_NOT_FOUND = 404
_NO_SUCH_OPERATION = 405  # no such operation on this path: the same answer as an unknown path
_TOO_LARGE = 413
_INVALID = 422

# Refusals answered with their own message as the reason.
_REFUSED_WITH_REASON: dict[type[Exception], int] = {
    ProjectNameRequiredError: _INVALID,
    PoiNameRequiredError: _INVALID,
    CoordinateOutOfRangeError: _INVALID,
    AnchorNotAPlaceError: _INVALID,
    UploadFormError: _INVALID,
    UploadTooLargeError: _TOO_LARGE,
}
# Unknown ids: a fixed message that never echoes the id.
_NOT_FOUND_MESSAGES: dict[type[Exception], str] = {
    ProjectNotFoundError: "Project not found",
    ItemNotFoundError: "Item not found",
}


def envelope(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


def _coded(status: int, message: str) -> JSONResponse:
    return envelope(status, _CODE_BY_STATUS[status], message)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def on_http_error(request: Request, error: HTTPException) -> Response:
        if not request.url.path.startswith("/api"):
            return await http_exception_handler(request, error)
        if error.status_code == _NO_SUCH_OPERATION:
            return _coded(_NOT_FOUND, "Not found")
        return envelope(error.status_code, _CODE_BY_STATUS.get(error.status_code, "not_found"), str(error.detail))

    @app.exception_handler(RequestValidationError)
    async def on_invalid_request(request: Request, error: RequestValidationError) -> Response:
        return _coded(_INVALID, f"Invalid request - {_problems(error)}")

    @app.exception_handler(TrackFilesRefusedError)
    async def on_refused_track_files(request: Request, error: TrackFilesRefusedError) -> Response:
        return _coded(_TOO_LARGE if error.too_large else _INVALID, str(error))

    async def on_refusal(request: Request, error: Exception) -> Response:
        return _coded(_registered(_REFUSED_WITH_REASON, error), str(error))

    async def on_unknown_id(request: Request, error: Exception) -> Response:
        return _coded(_NOT_FOUND, _registered(_NOT_FOUND_MESSAGES, error))

    for refusal in _REFUSED_WITH_REASON:
        app.add_exception_handler(refusal, on_refusal)
    for unknown in _NOT_FOUND_MESSAGES:
        app.add_exception_handler(unknown, on_unknown_id)


def _registered[T](table: dict[type[Exception], T], error: Exception) -> T:
    """The entry of the error's class, or of the nearest registered base class (Starlette's handler lookup order)."""
    return next(table[cls] for cls in type(error).__mro__ if cls in table)


def _problems(error: RequestValidationError) -> str:
    """`field: message` per problem, the `body` prefix of the location left out."""
    return "; ".join(
        f"{'.'.join(str(part) for part in problem['loc'] if part != 'body')}: {problem['msg']}"
        for problem in error.errors()
    )
