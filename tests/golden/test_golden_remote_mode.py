"""Remote mode of the golden-order check without a Pi (slice 03-ops; D175, step 06-05 runs it on planner-perf).

PLANNER_PERF_URL points at a fake planner: a local stub server answering the HTTP API calls the check makes
(brief §5) with a scripted stop order. The check must seed a '__perf golden' project there, plan only GOLDEN_INSTANCE,
pass on the golden sha and fail naming the instance and both hashes on any other.
"""

from __future__ import annotations

import itertools
import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.golden.test_golden_order import check_golden_orders
from tests.perf.golden_instances import COMMITTED, I2_SPARSE, committed_trip, order_sha256

GPX_NAME = re.compile(rb"<trk><name>(?P<name>[^<]+)</name>")


@dataclass
class StubPlanner:
    """What the fake planner was asked, and the order it answers every plan with."""

    order: list[str]
    projects: dict[str, dict[str, Any]] = field(default_factory=dict)
    calculations: list[dict[str, list[str]]] = field(default_factory=list)
    ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))

    def answer(self, method: str, path: str, query: dict[str, list[str]], body: bytes) -> tuple[int, Any]:
        parts = path.strip("/").split("/")
        if (method, parts) == ("GET", ["healthz"]):
            return 200, {"status": "ok"}
        if parts[:2] == ["api", "projects"] and len(parts) == 2:
            return self._projects(method, body)
        if parts[:2] == ["api", "projects"] and len(parts) == 4:
            return self._project(method, self.projects[parts[2]], parts[3], query, body)
        if (method, parts[:2]) == ("GET", ["api", "plan-jobs"]):
            return 200, {"job_id": parts[2], "state": "done", "plan_run_id": f"run-{parts[2]}", "elapsed_s": 4.2}
        if (method, parts[:2]) == ("GET", ["api", "plan-runs"]):
            stops = [{"name": name} for name in self.order]
            return 200, {"id": parts[2], "number": 1, "status": "ready", "stops": stops, "messages": []}
        return 404, {"code": "not_found", "message": f"{method} {path}"}

    def _projects(self, method: str, body: bytes) -> tuple[int, Any]:
        if method == "POST":
            project = {"id": str(next(self.ids)), "name": json.loads(body)["name"], "items": [], "runs": []}
            self.projects[project["id"]] = project
            return 201, {"id": project["id"], "name": project["name"]}
        return 200, [{"id": p["id"], "name": p["name"]} for p in self.projects.values()]

    def _project(
        self, method: str, project: dict[str, Any], what: str, query: dict[str, list[str]], body: bytes
    ) -> tuple[int, Any]:
        items: list[dict[str, Any]] = project["items"]
        if (method, what) == ("POST", "tracks"):
            items += [self._item("track", m["name"].decode()) for m in GPX_NAME.finditer(body)]
            return 201, items
        if (method, what) == ("POST", "pois"):
            items.append(self._item("poi", json.loads(body)["name"]))
            return 201, items[-1]
        if (method, what) == ("PUT", "anchors"):
            chosen = json.loads(body)
            for item in items:
                item["anchor"] = {chosen["start_item_id"]: "start", chosen["end_item_id"]: "end"}.get(item["id"])
            return 200, items
        if (method, what) == ("POST", "plan-runs"):
            self.calculations.append(query)
            project["runs"].append({"number": len(project["runs"]) + 1, "status": "ready"})
            return 202, {"job_id": str(next(self.ids)), "state": "queued"}
        if (method, what) == ("GET", "plan-runs"):
            return 200, project["runs"]
        return 200, items

    def _item(self, kind: str, name: str) -> dict[str, Any]:
        return {"id": str(next(self.ids)), "type": kind, "name": name, "included": True, "anchor": None}


def _handler(stub: StubPlanner) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            url = urlsplit(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            status, payload = stub.answer(self.command, url.path, parse_qs(url.query), body)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = _serve

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


@pytest.fixture
def golden_i2() -> list[str]:
    return list(committed_trip(COMMITTED / f"{I2_SPARSE}.json").expected_order)


@contextmanager
def _serve(stub: StubPlanner) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(stub))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _remote(url: str, summary: Path) -> dict[str, str]:
    return {"PLANNER_PERF_URL": url, "GOLDEN_INSTANCE": "i2", "GITHUB_STEP_SUMMARY": str(summary)}


def test_remote_mode_seeds_a_perf_project_plans_only_the_named_instance_and_passes_on_its_golden_sha(
    golden_i2: list[str], tmp_path: Path
) -> None:
    # bypass: an integration check of the remote wiring against one scripted planner; no input space to quantify.
    stub = StubPlanner(order=golden_i2)
    summary = tmp_path / "summary.md"

    with _serve(stub) as url:
        results = check_golden_orders(_remote(url, summary))

    assert [(r.kind, r.matches) for r in results] == [(I2_SPARSE, True)]
    names = [p["name"] for p in stub.projects.values()]
    assert len(names) == 1 and re.fullmatch(rf"__perf golden {I2_SPARSE} \d{{8}}-\d{{6}}", names[0]), names
    assert stub.calculations == [{"ignore_memo": ["true"]}]
    shown = summary.read_text(encoding="utf-8")
    assert order_sha256(golden_i2) in shown and "advisory" in shown and "4.2 (elapsed_s)" in shown


def test_remote_mode_fails_naming_the_instance_and_both_hashes_on_a_different_order(
    golden_i2: list[str], tmp_path: Path
) -> None:
    # bypass: as above; one different (still complete) order stands for every different one (hash injectivity, 06-01).
    different = [golden_i2[0], golden_i2[2], golden_i2[1], *golden_i2[3:]]
    stub = StubPlanner(order=different)

    with pytest.raises(AssertionError) as failed, _serve(stub) as url:
        check_golden_orders(_remote(url, tmp_path / "summary.md"))

    message = str(failed.value)
    assert I2_SPARSE in message and order_sha256(golden_i2) in message and order_sha256(different) in message
    assert "DIFFERENT" in (tmp_path / "summary.md").read_text(encoding="utf-8"), "the summary is written first"
