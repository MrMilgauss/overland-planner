"""The /api error envelope for failures no route expected (brief §5, D130, D183, D197).

Driving port: the HTTP surface of a small FastAPI app with the planner's `install_error_handlers` and routes that
fail on purpose (an unhandled exception, an `HTTPException` of a given status), under /api and outside it.
Observed: status, body and the events recorded through the `EventLog` port.
Example-based (# bypass: exact status/code table and fixed neutral message, not an input invariant).
Test Budget: 3 behaviors (unhandled error -> 500 envelope + one event, HTTPException status -> code, non-/api keeps
its body) x 2 = 6; 3 tests.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from overland_planner.adapters.http.errors import install_error_handlers
from tests.common.catalog_fakes import RecordingEventLog

SECRET = "hunter2-db-password"  # noqa: S105 - the text that must never leak
NEUTRAL = "Something went wrong on the planner - nothing was changed"


class _Boom(RuntimeError):
    pass


def _app(event_log: RecordingEventLog) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app, event_log)

    @app.get("/api/boom")
    def api_boom() -> None:
        raise _Boom(f"connection refused: {SECRET}")

    @app.get("/boom")
    def page_boom() -> None:
        raise _Boom(SECRET)

    @app.get("/api/status/{status}")
    def api_status(status: int) -> None:
        raise HTTPException(status_code=status, detail="why")

    return app


@pytest.fixture
def event_log() -> RecordingEventLog:
    return RecordingEventLog()


@pytest.fixture
def client(event_log: RecordingEventLog) -> TestClient:
    return TestClient(_app(event_log), raise_server_exceptions=False)


def test_an_unhandled_api_error_is_a_neutral_internal_error_envelope_and_one_event(
    client: TestClient, event_log: RecordingEventLog
) -> None:
    response = client.get("/api/boom")
    assert (response.status_code, response.json()) == (500, {"code": "internal_error", "message": NEUTRAL})
    assert event_log.events == [
        ("http.unhandled_error", {"error_class": "_Boom", "method": "GET", "path": "/api/boom"})
    ]
    assert SECRET not in response.text + repr(event_log.events)


@pytest.mark.parametrize(
    ("raised", "status", "code"),
    [
        (401, 401, "unauthorized"),
        (404, 404, "not_found"),
        (405, 404, "not_found"),
        (413, 413, "upload_too_large"),
        (422, 422, "validation_error"),
        (400, 400, "validation_error"),
        (409, 409, "validation_error"),
        (500, 500, "internal_error"),
        (503, 503, "internal_error"),
    ],
)
def test_an_api_http_exception_answers_the_code_of_its_status(
    client: TestClient, raised: int, status: int, code: str
) -> None:
    response = client.get(f"/api/status/{raised}")
    assert (response.status_code, set(response.json()), response.json()["code"]) == (status, {"code", "message"}, code)
    assert response.json()["message"]


def test_an_unhandled_error_outside_api_keeps_the_plain_server_error(
    client: TestClient, event_log: RecordingEventLog
) -> None:
    response = client.get("/boom")
    assert (response.status_code, response.text) == (500, "Internal Server Error")
    assert SECRET not in repr(event_log.events)
