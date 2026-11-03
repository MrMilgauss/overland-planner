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


def envelope(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def on_http_error(request: Request, error: HTTPException) -> Response:
        if not request.url.path.startswith("/api"):
            return await http_exception_handler(request, error)
        if error.status_code == 405:  # no such operation on this path: the same answer as an unknown path
            return envelope(404, "not_found", "Not found")
        return envelope(error.status_code, _CODE_BY_STATUS.get(error.status_code, "not_found"), str(error.detail))

    @app.exception_handler(RequestValidationError)
    async def on_invalid_request(request: Request, error: RequestValidationError) -> Response:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in e['loc'] if part != 'body')}: {e['msg']}" for e in error.errors()
        )
        return envelope(422, "validation_error", f"Invalid request - {problems}")

    @app.exception_handler(ProjectNameRequiredError)
    @app.exception_handler(PoiNameRequiredError)
    @app.exception_handler(CoordinateOutOfRangeError)
    @app.exception_handler(AnchorNotAPlaceError)
    async def on_refused_value(request: Request, error: ValueError) -> Response:
        return envelope(422, "validation_error", str(error))

    @app.exception_handler(TrackFilesRefusedError)
    async def on_refused_track_files(request: Request, error: TrackFilesRefusedError) -> Response:
        if error.too_large:
            return envelope(413, "upload_too_large", str(error))
        return envelope(422, "validation_error", str(error))

    @app.exception_handler(UploadTooLargeError)
    async def on_upload_too_large(request: Request, error: UploadTooLargeError) -> Response:
        return envelope(413, "upload_too_large", str(error))

    @app.exception_handler(UploadFormError)
    async def on_invalid_upload_form(request: Request, error: UploadFormError) -> Response:
        return envelope(422, "validation_error", str(error))

    @app.exception_handler(ProjectNotFoundError)
    async def on_unknown_project(request: Request, error: ProjectNotFoundError) -> Response:
        return envelope(404, "not_found", "Project not found")

    @app.exception_handler(ItemNotFoundError)
    async def on_unknown_item(request: Request, error: ItemNotFoundError) -> Response:
        return envelope(404, "not_found", "Item not found")
