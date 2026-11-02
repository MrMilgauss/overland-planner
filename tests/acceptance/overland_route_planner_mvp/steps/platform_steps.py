"""Platform steps: start-up, health, restarts, basic auth, deployment (US-01a, US-01b).

`@requires_external` steps run only with --run-external on the right host (Pi over ssh, Docker, amd64 PC);
their environment knobs are PLANNER_PI_SSH (default deploy@pi.example), PLANNER_PI_URL
(default http://pi.example:8080), PLANNER_PI_DIR (default ~/apps/overland-planner), PLANNER_IMAGE.
"""

from __future__ import annotations

import os
import platform
import re
import secrets
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from pytest_bdd import given, parsers, then, when

from tests.acceptance.overland_route_planner_mvp.steps.planner import ServerPlanner
from tests.acceptance.overland_route_planner_mvp.steps.world import CATALOG_UNIVERSE, PlannerWorld, assert_error_envelope
from tests.common.fakes import FakeMountTable
from tests.common.state_delta import assert_state_delta

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_FILE = REPO_ROOT / "deploy" / "compose.yaml"
FUTURE_REVISION = "f0f0f0f0f0f0"  # Alembic no-op stub revision standing for "a newer planner version" (waiver W3)
PI_SSH = os.environ.get("PLANNER_PI_SSH", "deploy@pi.example")
PI_URL = os.environ.get("PLANNER_PI_URL", "http://pi.example:8080")
PI_DIR = os.environ.get("PLANNER_PI_DIR", "~/apps/overland-planner")
PI_COMPOSE = f"cd {PI_DIR} && docker compose -p overland --env-file .env --env-file release.env"


def _run(command: list[str], timeout: float = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def _ssh(remote: str, timeout: float = 300) -> subprocess.CompletedProcess[str]:
    return _run(["ssh", "-o", "BatchMode=yes", PI_SSH, remote], timeout=timeout)


def _json_log_events(lines: list[str], event: str) -> list[dict[str, Any]]:
    import json

    found = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == event:
            found.append(record)
    return found


# ---------------------------------------------------------------------------- start the planner (server)
@given("Marco's planner is running on his home server with his trip collection saved there")
def given_marco_has_started_the_planner_server(world: PlannerWorld) -> None:
    world.planner = ServerPlanner(world.environ, REPO_ROOT)
    world.planner.start()


@given("Marco's data folder cannot be written to")
def given_data_folder_cannot_be_written(world: PlannerWorld) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("a read-only folder cannot be simulated as root")
    world.data_dir.chmod(0o555)


def _alembic_config(world: PlannerWorld, with_future: bool) -> Any:
    """Alembic configuration of the planner's own migrations (DESIGN `migrations/`), on Marco's data folder."""
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    locations = [str(REPO_ROOT / "migrations" / "versions")]
    if with_future:
        locations.append(str(world.scratch["future_versions"]))
    config.set_main_option("path_separator", "os")
    config.set_main_option("version_locations", os.pathsep.join(locations))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{world.data_dir / 'db' / 'planner.sqlite'}")
    return config


def _stamp(world: PlannerWorld, revision: str, with_future: bool) -> None:
    from alembic import command

    previous = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(world.data_dir)  # the planner's migration env may read its settings
    try:
        command.stamp(_alembic_config(world, with_future), revision, purge=True)
    finally:
        if previous is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = previous


@given(parsers.re(r'Marco\'s data folder holds the project "(?P<name>[^"]+)" saved by a newer planner version'))
def given_data_folder_from_newer_version(world: PlannerWorld, name: str) -> None:
    """Waiver W3: the data is created by the real planner; 'newer version' = an Alembic no-op revision on top of the
    planner's head, applied with Alembic's own stamp (no hand-written schema, review H-07)."""
    from alembic.script import ScriptDirectory

    server = ServerPlanner(world.environ, REPO_ROOT)
    world.planner = server
    server.start()
    response = world.note(world.marco().create_project(name))
    assert response.status_code == 201, f"precondition failed: could not create {name!r}: {response.text[:300]}"
    world.project_id, world.project_name = str(response.json()["id"]), name
    world.before = world.catalog_view()
    server.stop()
    head = ScriptDirectory.from_config(_alembic_config(world, with_future=False)).get_current_head()
    world.scratch["head"] = head
    future = world.tmp_path / "future_versions"
    future.mkdir(exist_ok=True)
    (future / f"{FUTURE_REVISION}_newer_planner.py").write_text(
        f'''"""A later planner version (test stub, no schema change)."""
revision = "{FUTURE_REVISION}"
down_revision = "{head}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
'''
    )
    world.scratch["future_versions"] = future
    _stamp(world, FUTURE_REVISION, with_future=True)


def start_planner_once(world: PlannerWorld) -> None:
    server = ServerPlanner(world.environ, REPO_ROOT, start_timeout_s=45.0)
    world.planner = server
    world.last_start = server.launch()
    if world.last_start.answered:
        server.stop()
    world.data_dir.chmod(0o755)


@when("Marco starts the planner")
def when_marco_starts_the_planner(world: PlannerWorld) -> None:
    start_planner_once(world)


@given("an older planner has refused to start on it")
def given_older_planner_refused(world: PlannerWorld) -> None:
    start_planner_once(world)
    refusals = world.last_start.events("health.startup.refused") if world.last_start else []
    assert not world.last_start.answered and len(refusals) == 1, (
        f"precondition failed: the older planner did not refuse to start\n{world.last_start.tail()}"
    )


@then("the planner refuses to start")
def then_the_planner_refuses_to_start(world: PlannerWorld) -> None:
    """A refusal is: no answer, a non-zero exit code, and exactly one `health.startup.refused` line (review L-07)."""
    record = world.last_start
    assert record is not None
    assert not record.answered, "the planner started and answered its health check"
    assert record.exit_code not in (None, 0), f"the planner did not stop with a failure (exit {record.exit_code})"
    refusals = record.events("health.startup.refused")
    assert len(refusals) == 1, f"expected one 'health.startup.refused' log line, found {len(refusals)}\n{record.tail()}"


@then("the planner log names the part that failed and the reason")
def then_log_names_part_and_reason(world: PlannerWorld) -> None:
    assert world.last_start is not None
    refusal = world.last_start.events("health.startup.refused")[0]
    assert refusal.get("component") and refusal.get("reason"), f"refusal line lacks component/reason: {refusal}"


@then("the planner log says the data is newer than this planner")
def then_log_says_data_is_newer(world: PlannerWorld) -> None:
    assert world.last_start is not None
    reasons = [r.get("reason") for r in world.last_start.events("health.startup.refused")]
    assert reasons == ["db_newer_than_app"], f"refusal reasons {reasons}\n{world.last_start.tail()}"


@when("Marco goes back to the newer planner")
def when_marco_goes_back_to_the_newer_planner(world: PlannerWorld) -> None:
    _stamp(world, world.scratch["head"], with_future=True)  # back to the version that saved the data (waiver W3)
    server = ServerPlanner(world.environ, REPO_ROOT)
    world.planner = server
    server.start()
    world.after = world.catalog_view()


@then(parsers.re(r'"(?P<name>[^"]+)" is exactly as he left it'))
def then_project_is_exactly_as_left(world: PlannerWorld, name: str) -> None:
    assert_state_delta(world.before, world.after, CATALOG_UNIVERSE, {})
    assert name in world.after["projects.names"]


# ------------------------------------------------------------------------------------------- restarts
@when("the planner is restarted")
def when_the_planner_is_restarted(world: PlannerWorld) -> None:
    assert world.planner is not None, "the planner is not running"
    world.before = world.catalog_view()
    world.planner.restart()
    world.after = world.catalog_view()


# ------------------------------------------------------------------------------------- health and pages
@then("the planner home page opens")
def then_the_home_page_opens(world: PlannerWorld) -> None:
    page = world.marco().home_page()
    assert page.status_code == 200, f"home page answered {page.status_code}"
    assert page.headers.get("content-type", "").startswith("text/html"), page.headers.get("content-type")


@then("the health check reports the planner as healthy")
def then_health_check_healthy(world: PlannerWorld) -> None:
    remote = world.scratch.get("remote_url")
    health = httpx.get(f"{remote}/healthz", timeout=10) if remote else world.marco().health()
    assert (health.status_code, health.json()) == (200, {"status": "ok"}), f"{health.status_code} {health.text}"


@then("each start-up was recorded as one line in the planner log")
def then_each_startup_one_log_line(world: PlannerWorld) -> None:
    assert isinstance(world.planner, ServerPlanner)
    for number, record in enumerate(world.planner.starts, start=1):
        started = record.events("app.started")
        assert len(started) == 1, f"start {number}: expected one 'app.started' line, found {len(started)}\n{record.tail()}"


@given("the planner was started on a data folder that would not survive a restart")
def given_started_on_non_persistent_folder(world: PlannerWorld) -> None:
    world.mount_table = FakeMountTable.with_mount(world.data_dir, "overlay")
    world.ensure_planner()


@when("Marco opens the planner home page")
def when_marco_opens_the_home_page(world: PlannerWorld) -> None:
    page = world.marco().home_page()
    assert page.status_code == 200, f"home page answered {page.status_code}"
    detail = world.marco().health_detail()
    world.seen_messages.extend(str(b) for b in detail.json().get("banners", []))


@then(parsers.re(r'he sees "(?P<message>.+)"'))
def then_he_sees(world: PlannerWorld, message: str) -> None:
    assert message in world.seen_messages, f"{message!r} not shown; Marco saw {world.seen_messages}"
    if world.response is not None and world.response.status_code >= 400:
        assert_error_envelope(world.response)
    world.scratch["last_message"] = message


@then("the health check reports unhealthy with the same reason")
def then_health_unhealthy_same_reason(world: PlannerWorld) -> None:
    health = world.marco().health()
    expected = {"status": "unhealthy", "reason": world.scratch["last_message"]}
    assert (health.status_code, health.json()) == (503, expected), f"{health.status_code} {health.text}"


# ---------------------------------------------------------------------------------------------- basic auth
@given(parsers.re(r'the shared household password is switched on in the settings for user "(?P<user>[^"]+)"'))
def given_basic_auth_enabled(world: PlannerWorld, user: str) -> None:
    password = "household-" + secrets.token_hex(4)
    world.environ.update({"PLANNER_BASIC_AUTH_USER": user, "PLANNER_BASIC_AUTH_PASSWORD": password})
    world.marco_auth = (user, password)
    world.ensure_planner()


@when("Giulia opens the planner from her iPhone without the password")
def when_giulia_opens_without_credentials(world: PlannerWorld) -> None:
    assert world.planner is not None
    giulia = world.planner.session(auth=None)
    world.giulia_responses = {"home": giulia.home_page(), "projects": giulia.projects(), "health": giulia.health()}


@when("Giulia opens the planner from her iPhone with a wrong password")
def when_giulia_opens_with_wrong_password(world: PlannerWorld) -> None:
    assert world.planner is not None and world.marco_auth is not None
    giulia = world.planner.session(auth=(world.marco_auth[0], world.marco_auth[1] + "-wrong"))
    world.giulia_responses = {"home": giulia.home_page(), "projects": giulia.projects(), "health": giulia.health()}


@then("she is asked to log in")
def then_she_is_asked_to_log_in(world: PlannerWorld) -> None:
    for page in ("home", "projects"):
        response = world.giulia_responses[page]
        assert response.status_code == 401, f"{page}: {response.status_code}"
        assert response.headers.get("www-authenticate", "").lower().startswith("basic"), response.headers
    assert_error_envelope(world.giulia_responses["projects"])


@then("no project data is shown")
def then_no_project_data_is_shown(world: PlannerWorld) -> None:
    assert world.project_name is not None
    for page in ("home", "projects"):
        assert world.project_name not in world.giulia_responses[page].text, f"{page} reveals {world.project_name!r}"


@then("the health check still answers without revealing any project")
def then_health_answers_without_projects(world: PlannerWorld) -> None:
    health = world.giulia_responses["health"]
    assert (health.status_code, health.json()) == (200, {"status": "ok"}), f"{health.status_code} {health.text}"


# --------------------------------------------------------------------------- deployment description (static)
@given("the planner set-up as delivered for the home server")
def given_the_planner_stack_as_delivered(world: PlannerWorld) -> None:
    world.scratch["compose_file"] = COMPOSE_FILE


@when("Marco checks what the set-up opens to the network by default")
def when_marco_checks_network_exposure(world: PlannerWorld) -> None:
    compose_file: Path = world.scratch["compose_file"]
    assert compose_file.exists(), f"the deployment description {compose_file.relative_to(REPO_ROOT)} is not delivered yet"
    world.scratch["compose"] = yaml.safe_load(compose_file.read_text()) or {}


def _services(world: PlannerWorld) -> dict[str, dict[str, Any]]:
    return dict(world.scratch["compose"].get("services", {}))


def _published(service: dict[str, Any]) -> list[tuple[str | None, str]]:
    """(host_ip, container_port) for every published port, short or long syntax."""
    published = []
    for port in service.get("ports", []) or []:
        if isinstance(port, dict):
            published.append((port.get("host_ip"), str(port.get("target"))))
            continue
        text = str(port)
        parts = re.split(r":(?![^{]*\})", text)  # keep ${VAR:-default} intact
        host_ip = parts[0] if len(parts) == 3 else None
        published.append((host_ip, parts[-1].split("/")[0]))
    return published


@then("only the planner itself can be reached from the home network, at its usual address")
def then_only_planner_reachable(world: PlannerWorld) -> None:
    default = {name: svc for name, svc in _services(world).items() if not svc.get("profiles")}
    exposed = {name: _published(svc) for name, svc in default.items() if _published(svc)}
    assert set(exposed) == {"planner"}, f"services reachable from the network by default: {sorted(exposed)}"
    assert [port for _, port in exposed["planner"]] == ["8080"], f"planner publishes {exposed['planner']}"


@then("the routing engine is never reachable from the network")
def then_routing_engine_not_reachable(world: PlannerWorld) -> None:
    for name, service in _services(world).items():
        if "valhalla" in name and "tunnel" not in name:
            assert not _published(service), f"{name} publishes {_published(service)}"


@then("the maintenance helpers listen only on the server itself, and only when started on purpose")
def then_helpers_loopback_only(world: PlannerWorld) -> None:
    for name, service in _services(world).items():
        published = _published(service)
        if name != "planner" and published:
            assert service.get("profiles"), f"{name} publishes ports without being behind a profile"
            assert all(ip == "127.0.0.1" for ip, _ in published), f"{name} publishes {published}"


# ------------------------------------------------------------------------- @requires_external: the Pi
@given("Marco has copied the planner set-up and his settings file to his Raspberry Pi")
def given_stack_copied_to_pi(world: PlannerWorld) -> None:
    check = _ssh(f"test -f {PI_DIR}/.env && test -f {PI_DIR}/compose.yaml && echo present", timeout=30)
    if "present" not in check.stdout:
        pytest.skip(f"the planner stack is not installed on {PI_SSH}:{PI_DIR} (run make deploy first)")


@when("he starts the planner on the Pi with one command")
def when_he_starts_the_stack_on_the_pi(world: PlannerWorld) -> None:
    world.scratch["pi_since"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    result = _ssh(f"{PI_COMPOSE} up -d --wait --force-recreate planner", timeout=300)
    assert result.returncode == 0, f"the stack did not start on the Pi:\n{result.stderr[-2000:]}"


def _pi_auth() -> tuple[str, str] | None:
    user, password = os.environ.get("PLANNER_PI_USER"), os.environ.get("PLANNER_PI_PASSWORD")
    return (user, password) if user and password else None


@then(parsers.re(r'the planner home page opens at "(?P<address>[^"]+)" in his desktop browser'))
def then_home_page_opens_at(world: PlannerWorld, address: str) -> None:
    base = f"http://{address}:{os.environ.get('PLANNER_PORT', '8080')}"  # the port lives in step code only (N-01)
    page = httpx.get(f"{base}/", auth=_pi_auth(), timeout=10)
    assert page.status_code == 200 and page.headers.get("content-type", "").startswith("text/html")
    world.scratch["remote_url"] = base


@then("the start-up is recorded as one line in the planner log")
def then_remote_startup_one_line(world: PlannerWorld) -> None:
    health = httpx.get(f"{world.scratch.get('remote_url', PI_URL)}/healthz", timeout=10)
    assert (health.status_code, health.json()) == (200, {"status": "ok"})
    logs = _ssh(f"{PI_COMPOSE} logs --no-log-prefix --since {world.scratch['pi_since']} planner", timeout=60)
    started = _json_log_events(logs.stdout.splitlines(), "app.started")
    assert len(started) == 1, f"expected one app.started line since the start, found {len(started)}"


@given("the planner has been idle for 10 minutes on the Pi")
def given_idle_for_ten_minutes(world: PlannerWorld) -> None:
    started = _ssh(f"{PI_COMPOSE} ps --format '{{{{.RunningFor}}}}' planner", timeout=30).stdout
    if not re.search(r"(\d{2,}|[1-9]\d*) (minutes|hours|days)|About an hour", started) or re.search(r"\b[1-9] minutes", started):
        pytest.skip(f"the planner has not been idle for 10 minutes yet ({started.strip()!r})")


@when("Marco checks the planner's memory use, not counting the routing engine")
def when_marco_checks_memory_use(world: PlannerWorld) -> None:
    stats = _ssh("docker stats --no-stream --format '{{.Name}} {{.MemUsage}}'", timeout=60).stdout
    line = next((ln for ln in stats.splitlines() if ln.startswith("overland-planner-")), "")
    match = re.search(r"([\d.]+)\s*(MiB|GiB|kB|KiB)", line)
    assert match, f"no memory figure for the planner in: {stats!r}"
    value, unit = float(match.group(1)), match.group(2)
    world.scratch["memory_mb"] = value * {"MiB": 1.048576, "GiB": 1073.741824, "kB": 0.001, "KiB": 0.001024}[unit]


@then(parsers.re(r"it uses less than (?P<limit>\d+) MB"), converters={"limit": float})
def then_it_uses_less_than(world: PlannerWorld, limit: float) -> None:
    assert world.scratch["memory_mb"] < limit, f"the idle planner uses {world.scratch['memory_mb']:.0f} MB"


# ----------------------------------------------------------------------- @requires_external: PC + Docker
def _require_docker() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker is not available on this host")


@given("Marco uses the same planner set-up and settings file on his amd64 PC")
def given_same_stack_on_pc(world: PlannerWorld) -> None:
    _require_docker()
    if platform.machine().lower() not in ("x86_64", "amd64"):
        pytest.skip(f"not an amd64 host ({platform.machine()})")


@when("he starts the planner on the PC with one command")
def when_he_starts_the_stack_on_the_pc(world: PlannerWorld) -> None:
    env = {**os.environ, "PLANNER_BIND": "127.0.0.1", "ROUTING_PROVIDER": "mock"}
    command = ["docker", "compose", "-p", "overland-pc-check", "-f", str(COMPOSE_FILE), "up", "-d", "--wait"]
    result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=600, check=False)
    world.scratch["pc_teardown"] = ["docker", "compose", "-p", "overland-pc-check", "-f", str(COMPOSE_FILE), "down", "-v"]
    assert result.returncode == 0, f"the stack did not start on the PC:\n{result.stderr[-2000:]}"


@then("the planner home page opens on the PC")
def then_home_page_opens_on_pc(world: PlannerWorld) -> None:
    try:
        page = httpx.get("http://127.0.0.1:8080/", timeout=10)
        assert page.status_code == 200 and page.headers.get("content-type", "").startswith("text/html")
    finally:
        _run(world.scratch["pc_teardown"], timeout=300)


@given("Marco's settings file contains the shared household password")
def given_settings_file_with_password(world: PlannerWorld) -> None:
    _require_docker()
    settings_file = REPO_ROOT / ".env"
    if settings_file.exists():
        pytest.skip("a real .env exists in the build folder; refusing to overwrite it")
    world.scratch["password"] = "secret-" + secrets.token_hex(12)
    settings_file.write_text(f"PLANNER_BASIC_AUTH_USER=ferri\nPLANNER_BASIC_AUTH_PASSWORD={world.scratch['password']}\n")
    world.scratch["settings_file"] = settings_file


@when("anyone inspects the packaged planner built from Marco's folder")
def when_anyone_inspects_the_image(world: PlannerWorld) -> None:
    tag = "overland-planner:secret-check"
    try:
        build = _run(["docker", "build", "-t", tag, str(REPO_ROOT)], timeout=1800)
        assert build.returncode == 0, f"image build failed:\n{build.stderr[-2000:]}"
        saved = subprocess.run(["docker", "image", "save", tag], capture_output=True, timeout=600, check=False)
        history = _run(["docker", "history", "--no-trunc", tag]).stdout
        inspect = _run(["docker", "image", "inspect", tag]).stdout
        world.scratch["image_text"] = (saved.stdout, history + inspect)
    finally:
        world.scratch["settings_file"].unlink(missing_ok=True)


@then("the password is not found in it")
def then_password_not_found(world: PlannerWorld) -> None:
    layers, metadata = world.scratch["image_text"]
    password: str = world.scratch["password"]
    assert password.encode() not in layers, "the password is inside an image layer"
    assert password not in metadata, "the password is in the image history or configuration"


# ------------------------------------------------------------- @requires_external: container without volume
@given("the packaged planner was started without its data storage")
def given_container_without_volume(world: PlannerWorld) -> None:
    _require_docker()
    image = os.environ.get("PLANNER_IMAGE")
    if not image:
        pytest.skip("set PLANNER_IMAGE to the image under test")
    run = _run(["docker", "run", "-d", "--rm", "-p", "127.0.0.1:18085:8080", "-e", "ROUTING_PROVIDER=mock", image])
    assert run.returncode == 0, run.stderr
    world.scratch["container_id"] = run.stdout.strip()


@when("Marco asks the planner whether it is healthy")
def when_marco_asks_whether_healthy(world: PlannerWorld) -> None:
    deadline, response = time.monotonic() + 120, None
    try:
        while time.monotonic() < deadline:
            try:
                response = httpx.get("http://127.0.0.1:18085/healthz", timeout=2)
                break
            except httpx.TransportError:
                time.sleep(1)
    finally:
        _run(["docker", "rm", "-f", world.scratch["container_id"]])
    assert response is not None, "the planner container never answered"
    world.scratch["container_health"] = response


@then(parsers.re(r'the health check reports unhealthy with "(?P<reason>.+)"'))
def then_health_unhealthy_with(world: PlannerWorld, reason: str) -> None:
    response = world.scratch["container_health"]
    assert (response.status_code, response.json()) == (503, {"status": "unhealthy", "reason": reason})

