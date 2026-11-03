"""DORA metrics from releases.log (D101, D176; kpi-contracts.yaml delivery_metrics), through the dora.py CLI.

Unit level: properties over generated releases.log files, through `dora.py main([... "--json"])` (the CLI entry `make
dora` runs); state-delta over the observable metric slots of both windows. Integration: one `make dora` run.
"""

from __future__ import annotations

import contextlib
import functools
import importlib.util
import io
import json
import random
import re
import statistics
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.common.state_delta import assert_state_delta, set_to, unchanged

REPO = Path(__file__).resolve().parents[2]
DORA = REPO / "deploy" / "scripts" / "dora.py"
SAMPLE = Path(__file__).resolve().parent / "fixtures" / "releases-sample.log"
NOW = datetime(2027, 1, 1, tzinfo=UTC)
WINDOWS = ("last_30_days", "all")
SLOTS = (
    "deployment_frequency",
    "lead_time_median_s",
    "change_failures",
    "deploy_attempts",
    "change_failure_rate",
    "time_to_restore_median_s",
    "unrestored_failures",
)
UNIVERSE = {f"{window}.{slot}" for window in WINDOWS for slot in SLOTS} | {"ignored_lines"}


@functools.cache
def _dora() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dora", DORA)
    assert spec is not None and spec.loader is not None, f"{DORA} missing"
    module = importlib.util.module_from_spec(spec)
    sys.modules["dora"] = module  # dataclasses resolve their module while the file executes
    spec.loader.exec_module(module)
    return module


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@st.composite
def log_lines(draw: st.DrawFn) -> str:
    """One releases.log line as deploy.sh / rollback.sh write it, or a damaged one (hand edits, truncated writes)."""
    if draw(st.integers(0, 9)) == 0:
        return draw(st.sampled_from(["", "not json", "{}", '{"ts":"yesterday","action":"deploy"}', '{"ts":']))
    ts = NOW - timedelta(seconds=draw(st.integers(3600, 90 * 86400)))
    lead = draw(st.integers(-3600, 3 * 86400))  # negative: a skewed clock wrote a commit_ts after the deploy
    commit_ts = draw(st.one_of(st.just(_stamp(ts - timedelta(seconds=lead))), st.sampled_from(["", "garbage"])))
    record = {
        "ts": _stamp(ts),
        "action": draw(st.sampled_from(["deploy", "deploy", "auto-rollback", "rollback"])),
        "digest": "sha256:" + draw(st.sampled_from("01ab")) * 64,
        "git_sha": draw(st.sampled_from("01ab")) * 40,
        "commit_ts": commit_ts,
        "alembic_head": "0001_initial",
        "result": draw(st.sampled_from(["ok", "ok", "failed", "unchanged", "aborted"])),
        "reason": "",
    }
    return json.dumps(record)


releases_logs = st.lists(log_lines(), max_size=40)


def metrics(lines: list[str], tmp: Path, universe: set[str] = UNIVERSE) -> dict[str, Any]:
    """The `universe` slots of what `dora.py --json` reports for a releases.log holding `lines`."""
    log = tmp / "releases.log"
    log.write_text("".join(line + "\n" for line in lines))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = _dora().main([str(log), "--json", "--now", _stamp(NOW)])
    assert status == 0
    report = json.loads(out.getvalue())
    flat = {f"{window}.{slot}": report[window][slot] for window in WINDOWS for slot in SLOTS}
    slots = {**flat, "ignored_lines": report["ignored_lines"]}
    return {key: slots[key] for key in universe}


def _every_slot(slot: str, check: Callable[[Any, Any], bool]) -> dict[str, Callable[[Any, Any], bool]]:
    return {f"{window}.{slot}": check for window in WINDOWS}


@given(lines=releases_logs)
@settings(max_examples=150, deadline=None)
def test_change_failure_rate_is_a_fraction(lines: list[str], tmp_path_factory: Any) -> None:
    tmp = tmp_path_factory.mktemp("dora")
    universe = {f"{window}.change_failure_rate" for window in WINDOWS}
    before, after = metrics([], tmp, universe), metrics(lines, tmp, universe)

    assert_state_delta(
        before,
        after,
        universe=universe,
        expected=_every_slot("change_failure_rate", lambda _old, new: new is None or 0.0 <= new <= 1.0),
        strict=True,
    )


@given(lines=releases_logs)
@settings(max_examples=150, deadline=None)
def test_lead_time_is_never_negative(lines: list[str], tmp_path_factory: Any) -> None:
    tmp = tmp_path_factory.mktemp("dora")
    never_negative = {
        **_every_slot("lead_time_median_s", lambda _old, new: new is None or new >= 0),
        **_every_slot("time_to_restore_median_s", lambda _old, new: new is None or new >= 0),
    }
    before, after = metrics([], tmp, set(never_negative)), metrics(lines, tmp, set(never_negative))

    assert_state_delta(before, after, universe=set(never_negative), expected=never_negative, strict=True)


@given(lines=releases_logs, seed=st.integers())
@settings(max_examples=150, deadline=None)
def test_metrics_ignore_line_order(lines: list[str], seed: int, tmp_path_factory: Any) -> None:
    tmp = tmp_path_factory.mktemp("dora")
    shuffled = lines[:]
    random.Random(seed).shuffle(shuffled)  # noqa: S311 - a test permutation

    assert_state_delta(metrics(lines, tmp), metrics(shuffled, tmp), universe=UNIVERSE, expected={}, strict=True)


@given(lines=releases_logs, result=st.sampled_from(["ok", "failed"]))
@settings(max_examples=150, deadline=None)
def test_an_auto_rollback_counts_as_one_failed_deploy(lines: list[str], result: str, tmp_path_factory: Any) -> None:
    tmp = tmp_path_factory.mktemp("dora")
    auto_rollback = json.dumps(
        {
            "ts": _stamp(NOW - timedelta(minutes=1)),  # newer than every generated line, inside both windows
            "action": "auto-rollback",
            "digest": "sha256:" + "c" * 64,
            "git_sha": "c" * 40,
            "commit_ts": _stamp(NOW - timedelta(minutes=30)),
            "alembic_head": "0001_initial",
            "result": result,
            "reason": "loopback smoke: /healthz did not answer 200",
        }
    )
    before = metrics(lines, tmp)
    after = metrics([*lines, auto_rollback], tmp)

    expected: dict[str, Callable[[Any, Any], bool]] = {}
    for window in WINDOWS:
        failures, attempts = before[f"{window}.change_failures"] + 1, before[f"{window}.deploy_attempts"] + 1
        expected[f"{window}.change_failures"] = set_to(failures)
        expected[f"{window}.deploy_attempts"] = set_to(attempts)
        expected[f"{window}.change_failure_rate"] = set_to(pytest.approx(failures / attempts))
        if result == "ok":  # it restored a healthy release itself, and with it every failure still open
            expected[f"{window}.unrestored_failures"] = lambda _old, new: new == 0
            expected[f"{window}.time_to_restore_median_s"] = lambda _old, new: new is not None and new >= 0
        else:
            expected[f"{window}.unrestored_failures"] = lambda old, new: new == old + 1
            expected[f"{window}.time_to_restore_median_s"] = unchanged()
    assert_state_delta(before, after, universe=UNIVERSE, expected=expected, strict=True)


def _line(ts: str, action: str, result: str, commit_ts: str) -> str:
    return json.dumps(
        {
            "ts": ts,
            "action": action,
            "digest": "sha256:" + "a" * 64,
            "git_sha": "a" * 40,
            "commit_ts": commit_ts,
            "alembic_head": "0002_projects",
            "result": result,
            "reason": "",
        }
    )


def test_make_dora_reports_the_four_metrics_from_the_copied_log(tmp_path: Path) -> None:
    # bypass: integration test of the `make dora` wiring - one representative releases.log is enough.
    log = tmp_path / "releases.log"
    log.write_text(
        "\n".join(
            [
                _line("2026-11-01T09:30:00Z", "deploy", "ok", "2026-11-01T09:00:00Z"),  # lead time 30 min
                _line("2026-11-02T09:50:00Z", "deploy", "ok", "2026-11-02T09:00:00Z"),  # lead time 50 min
                _line("2026-11-02T10:02:00Z", "rollback", "ok", "2026-11-01T09:00:00Z"),  # restores after 12 min
                _line("2026-11-02T11:00:00Z", "deploy", "unchanged", "2026-11-01T09:00:00Z"),  # not a deploy
            ]
        )
        + "\n"
    )

    result = subprocess.run(
        ["make", "-s", "-C", str(REPO), "dora", f"RELEASES_LOG={log}"], capture_output=True, text=True, timeout=120
    )

    assert result.returncode == 0, result.stderr
    report = result.stdout
    assert "Deployment frequency" in report and "2 deploys" in report
    assert "Lead time for changes" in report and "40 min" in report  # median of 30 and 50 min
    assert "Change failure rate" in report and "50% (1/2)" in report  # the 50-min deploy was rolled back in 24 h
    assert "Time to restore" in report and "12 min" in report


@st.composite
def deploys_with_offset_commit_ts(draw: st.DrawFn) -> tuple[str, int]:
    """An ok deploy line whose ts and commit_ts (git %cI) carry arbitrary UTC offsets, and its true lead time in s."""
    ts = NOW - timedelta(seconds=draw(st.integers(3600, 29 * 86400)))
    lead = draw(st.integers(0, 3 * 86400))
    zones = st.integers(-14 * 60, 14 * 60).map(lambda minutes: timezone(timedelta(minutes=minutes)))
    deploy_zone, commit_zone = draw(zones), draw(zones)
    commit_ts = (ts - timedelta(seconds=lead)).astimezone(commit_zone).isoformat()
    deploy_ts = ts.astimezone(deploy_zone).isoformat().replace("+00:00", "Z")
    return _line(deploy_ts, "deploy", "ok", commit_ts), lead


@given(deploys=st.lists(deploys_with_offset_commit_ts(), min_size=1, max_size=12))
@settings(max_examples=150, deadline=None)
def test_lead_time_is_absolute_whatever_the_utc_offsets(deploys: list[tuple[str, int]], tmp_path_factory: Any) -> None:
    tmp = tmp_path_factory.mktemp("dora")
    lines, leads = [line for line, _ in deploys], [lead for _, lead in deploys]
    before, after = metrics([], tmp), metrics(lines, tmp)

    expected: dict[str, Callable[[Any, Any], bool]] = {}
    for window in WINDOWS:
        expected[f"{window}.deployment_frequency"] = set_to(len(deploys))
        expected[f"{window}.deploy_attempts"] = set_to(len(deploys))
        expected[f"{window}.change_failure_rate"] = set_to(0.0)
        expected[f"{window}.lead_time_median_s"] = set_to(statistics.median(leads))  # none dropped, none negative
    assert_state_delta(before, after, universe=UNIVERSE, expected=expected, strict=True)


def test_make_dora_on_the_real_pi_sample_reports_the_four_metrics() -> None:
    # bypass: regression on the releases.log the slice-00b gate wrote on the Pi (git %cI commit_ts in +01:00).
    def dora(*options: str) -> str:
        command = [sys.executable, str(DORA), str(SAMPLE), "--now", "2026-11-04T00:00:00Z", *options]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        assert result.returncode == 0, result.stderr
        return result.stdout

    report = json.loads(dora("--json"))
    for window in WINDOWS:
        assert report[window] == {
            "deployment_frequency": 4,
            "lead_time_median_s": 858.5,  # median of 17:31, 21:35, 9:22 and 11:06 (deploy ts - commit ts)
            "change_failures": 1,  # the 18:39:48 deploy, rolled back 20 s later
            "deploy_attempts": 4,
            "change_failure_rate": 0.25,
            "time_to_restore_median_s": 20.0,
            "unrestored_failures": 0,
        }
    assert report["ignored_lines"] == 0

    header, *rows = dora().splitlines()[1:]
    all_column = header.index("all")
    for row in rows:
        label, last_30_days, whole_log = re.split(r"\s{2,}", row)
        assert row.index(whole_log, len(label) + len(last_30_days)) == all_column, row
    assert "14 min median" in rows[1] and "20 s median, 0 unrestored" in rows[3]
