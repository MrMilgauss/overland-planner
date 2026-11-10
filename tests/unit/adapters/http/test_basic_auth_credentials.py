"""Shared household password properties (brief §12, §5; ADR-011 Amendment 1; D98).

Driving port: the HTTP surface of the planner guarded by `BasicAuthMiddleware` around the real application from the
production composition root (built once per module, auth off). Marco's view of the catalog is read through the
unguarded application, so the universe is what he observes: the project list and the open project's items.
The `EventLog` (`StructlogEventLog.info` / `.warning`) is the driving port of the redaction property.
Test Budget: 4 behaviors (access iff exact credentials, refusal answer per path family, /healthz open,
password never logged) x 2 = 8; 4 property tests.
"""

from __future__ import annotations

import base64
import json
import string
import unicodedata
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from overland_planner.adapters.http.basic_auth import BasicAuthCredentials, BasicAuthMiddleware
from overland_planner.adapters.logging.structlog_event_log import StructlogEventLog
from overland_planner.bootstrap.app_factory import ExternalPorts, create_app
from tests.common.fakes import FakeClock
from tests.common.state_delta import assert_state_delta, set_to, unchanged
from tests.common.workspace import workspace_data_dir

UNIVERSE = {"projects.names", "project.items"}
FIXED_PROJECT = "Alpi Occidentali giugno 2027"

_char = st.characters(exclude_categories=("Cs",), exclude_characters="\x00")
users = st.text(_char.filter(lambda c: c != ":"), min_size=1, max_size=12)
passwords = st.text(_char, min_size=1, max_size=16)


@pytest.fixture(scope="module")
def planner() -> Iterator[tuple[FastAPI, str]]:
    """The real planner (auth off) on a workspace data folder (never the OS temp folder, ADR-011 D121)."""
    with workspace_data_dir("unit") as folder:
        app = create_app(
            {"DATA_DIR": str(folder), "ROUTING_PROVIDER": "mock"}, external=ExternalPorts(clock=FakeClock())
        )
        project_id = TestClient(app).post("/api/projects", json={"name": FIXED_PROJECT}).json()["id"]
        yield app, project_id


def marco_view(app: FastAPI, project_id: str) -> dict[str, Any]:
    marco = TestClient(app)
    return {
        "projects.names": tuple(sorted(p["name"] for p in marco.get("/api/projects").json())),
        "project.items": tuple(
            json.dumps(i, sort_keys=True) for i in marco.get(f"/api/projects/{project_id}/items").json()
        ),
    }


def basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(user.encode() + b":" + password.encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _swapcase(text: str) -> str:
    return text.swapcase()


def _other_normal_form(text: str) -> str:
    nfc = unicodedata.normalize("NFC", text)
    return unicodedata.normalize("NFD", text) if text == nfc else nfc


@st.composite
def presentations(draw: st.DrawFn, user: str, password: str) -> tuple[str, dict[str, str]]:
    """What a browser may send: the exact pair, near misses of either part, nothing, or a malformed header."""
    kind = draw(
        st.sampled_from(["exact", "prefix", "extended", "case", "normal_form", "empty", "other", "absent", "malformed"])
    )
    part = draw(st.sampled_from(["user", "password"]))
    if kind == "absent":
        return kind, {}
    if kind == "malformed":
        return kind, {"Authorization": draw(st.sampled_from(["Basic", "Basic !!!", "Bearer abc", "Basic Zm9v"]))}
    alter = {
        "exact": lambda text: text,
        "prefix": lambda text: text[:-1],
        "extended": lambda text: text + draw(_char.filter(lambda c: c != ":")),
        "case": _swapcase,
        "normal_form": _other_normal_form,
        "empty": lambda _text: "",
        "other": lambda _text: draw(users),
    }[kind]
    presented_user, presented_password = (alter(user), password) if part == "user" else (user, alter(password))
    return f"{kind}:{part}:{(presented_user, presented_password) == (user, password)}", basic(
        presented_user, presented_password
    )


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow], deadline=None)
@given(data=st.data(), user=users, password=passwords)
def test_a_change_is_made_only_with_the_configured_user_and_exact_password(
    planner: tuple[FastAPI, str], data: st.DataObject, user: str, password: str
) -> None:
    app, project_id = planner
    label, headers = data.draw(presentations(user, password), label="presented")
    admitted = label.endswith(":True")
    guarded = TestClient(BasicAuthMiddleware(app, credentials=BasicAuthCredentials(user, password)))
    name = f"Trip {uuid.uuid4().hex[:8]}"

    before = marco_view(app, project_id)
    answer = guarded.post("/api/projects", json={"name": name}, headers=headers)
    after = marco_view(app, project_id)

    assert answer.status_code == (201 if admitted else 401), (label, answer.text)
    expected_names = set_to(tuple(sorted((*before["projects.names"], name)))) if admitted else unchanged()
    assert_state_delta(
        before,
        after,
        universe=UNIVERSE,
        expected={"projects.names": expected_names, "project.items": unchanged()},
        strict=True,
    )


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow], deadline=None)
@given(
    user=users,
    password=passwords,
    path=st.sampled_from(["/", "/index.html", "/assets/index.js", "/api/health", "/api/projects", "/api/{id}/items"]),
    wrong=st.booleans(),
)
def test_every_page_but_the_liveness_check_asks_to_log_in(
    planner: tuple[FastAPI, str], user: str, password: str, path: str, wrong: bool
) -> None:
    app, project_id = planner
    guarded = TestClient(BasicAuthMiddleware(app, credentials=BasicAuthCredentials(user, password)))
    url = path.replace("/api/{id}", f"/api/projects/{project_id}")

    answer = guarded.get(url, headers=basic(user, password + "x") if wrong else {})

    assert answer.status_code == 401
    assert answer.headers["www-authenticate"].startswith('Basic realm="')
    assert FIXED_PROJECT not in answer.text
    if url.startswith("/api"):
        assert answer.json()["code"] == "unauthorized"
    else:
        assert not answer.headers["content-type"].startswith("application/json")


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(user=users, password=passwords, with_credentials=st.booleans())
def test_the_liveness_check_answers_without_credentials(
    planner: tuple[FastAPI, str], user: str, password: str, with_credentials: bool
) -> None:
    app, _ = planner
    guarded = TestClient(BasicAuthMiddleware(app, credentials=BasicAuthCredentials(user, password)))

    answer = guarded.get("/healthz", headers=basic(user, "nope") if with_credentials else {})

    assert (answer.status_code, answer.json()) == (200, {"status": "ok"})


_field_names = st.sampled_from(["reason", "detail", "password", "authorization", "Authorization", "header"])


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    # A non-ASCII character keeps the password from matching the line's own keys, values or JSON punctuation.
    password=st.text(_char, min_size=1, max_size=16).filter(lambda p: any(c not in string.printable for c in p)),
    fields=st.dictionaries(_field_names, st.text(string.ascii_lowercase, max_size=10), max_size=4),
    level=st.sampled_from(["info", "warning"]),
)
def test_the_password_never_appears_in_an_event_line(
    capsys: pytest.CaptureFixture[str], password: str, fields: dict[str, str], level: str
) -> None:
    capsys.readouterr()
    log = StructlogEventLog(FakeClock(), app_version="dev", secret=password)
    leaking: dict[str, object] = {name: f"{value}{password}{value}" for name, value in fields.items()}
    leaking["nested"] = {"items": [password, {"authorization": "Basic abc"}]}

    getattr(log, level)("security.probe", **leaking)

    (line,) = capsys.readouterr().out.splitlines()
    record = json.loads(line)
    assert password not in line and json.dumps(password)[1:-1] not in line
    assert record["level"] == level and record["event"] == "security.probe"
    assert all(record[name] == "[redacted]" for name in leaking if name.lower() in {"password", "authorization"})
    assert record["nested"]["items"][1]["authorization"] == "[redacted]"
