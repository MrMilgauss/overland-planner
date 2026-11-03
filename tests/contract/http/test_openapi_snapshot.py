"""HTTP contract (brief §5, D130, D183): the committed OpenAPI snapshot and the /api error envelope.

Driving port: the real composition root `create_app`. Any API change fails `test_openapi_matches_the_snapshot`
until the snapshot is regenerated on purpose: `make openapi-snapshot` (runs this module as a script).
Contract level: single examples per route/status, not input invariants.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from overland_planner.bootstrap.app_factory import create_app

SNAPSHOT = Path(__file__).with_name("openapi.json")
ERROR_CODES = {
    401: {"unauthorized"},
    404: {"not_found"},
    413: {"upload_too_large"},
    422: {"validation_error"},
    500: {"internal_error"},
}
UNKNOWN_ID = "0" * 32


def _openapi(data_dir: Path) -> dict[str, Any]:
    # A fixed environment so the snapshot does not depend on the caller's PLANNER_GIT_SHA (info.version).
    return create_app({"DATA_DIR": str(data_dir), "ROUTING_PROVIDER": "mock"}).openapi()


def _render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def test_openapi_matches_the_snapshot(tmp_path: Path) -> None:
    assert _render(_openapi(tmp_path)) == SNAPSHOT.read_text(), (
        "the API changed; regenerate the snapshot on purpose with `make openapi-snapshot` and commit it"
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app({"DATA_DIR": str(tmp_path), "ROUTING_PROVIDER": "mock"}))


@pytest.mark.parametrize(
    ("method", "path", "body", "status", "code"),
    [
        ("GET", "/api/no-such-thing", None, 404, "not_found"),
        ("DELETE", "/api/projects", None, 404, "not_found"),
        ("GET", f"/api/projects/{UNKNOWN_ID}", None, 404, "not_found"),
        ("GET", f"/api/projects/{UNKNOWN_ID}/items", None, 404, "not_found"),
        ("POST", "/api/projects", {}, 422, "validation_error"),
        ("POST", "/api/projects", {"name": " "}, 422, "validation_error"),
    ],
)
def test_every_api_error_is_the_envelope_with_the_code_of_its_status(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None, status: int, code: str
) -> None:
    response = client.request(method, path, json=body)
    assert (response.status_code, set(response.json())) == (status, {"code", "message"})
    assert response.json()["code"] == code and code in ERROR_CODES[status]
    assert response.json()["message"]


def test_an_unhandled_api_error_is_the_internal_error_envelope(tmp_path: Path) -> None:
    app = create_app({"DATA_DIR": str(tmp_path), "ROUTING_PROVIDER": "mock"})

    def broken() -> None:
        raise RuntimeError("never shown")

    app.add_api_route("/api/broken", broken)
    app.router.routes.insert(0, app.router.routes.pop())  # ahead of the web page mount
    response = TestClient(app, raise_server_exceptions=False).get("/api/broken")
    assert (response.status_code, response.json()["code"]) == (500, "internal_error")
    assert "never shown" not in response.text


def test_healthz_keeps_its_own_body(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


if __name__ == "__main__":  # `make openapi-snapshot`
    with tempfile.TemporaryDirectory() as folder:
        SNAPSHOT.write_text(_render(_openapi(Path(folder))))
    sys.stdout.write(f"openapi snapshot written to {SNAPSHOT}\n")
