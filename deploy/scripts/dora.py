#!/usr/bin/env python3
"""`make dora` on the Mac: the four DORA metrics from the copied releases.log (D101, D176; stdlib only).

    dora.py [RELEASES_LOG] [--json] [--now 2026-11-03T08:00:00Z]

releases.log is the one-JSON-object-per-line history deploy.sh and rollback.sh append on the Pi (ts, action, digest,
git_sha, commit_ts, alembic_head, result, reason); `make deploy` and `make rollback` copy it to
.data/ops/releases.log. Definitions (docs/product/kpi-contracts.yaml delivery_metrics), for the last 30 days and
for the whole log:

D-1 Deployment frequency: deploy lines with result ok (unchanged, aborted and failed excluded).
D-2 Lead time for changes: median of (ts - commit_ts) over those deploys; a deploy whose commit_ts is missing or
    later than its ts (clock skew) has no lead time and is left out.
D-3 Change failure rate: failed changes / deploy attempts. Attempts are successful deploys, refused deploys
    (deploy failed) and auto-rollback lines (deploy.sh writes one auto-rollback line, never a deploy line, for an
    attempt it rolled back). Failed changes are the auto-rollback lines plus the successful deploys followed by a
    manual rollback (ok or failed) within 24 h; each counts once.
D-4 Time to restore: median of (ts of the first later ok rollback, auto-rollback or deploy - ts of the failure); an
    auto-rollback ok restored at once (0 s). Failures not restored yet are reported as unrestored.

Lines are ordered by ts (ties by content), so the metrics never depend on the order of the lines in the file.
Unreadable lines are counted as ignored and never stop the report.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_LOG = ".data/ops/releases.log"
WINDOW = timedelta(days=30)
MANUAL_ROLLBACK_WINDOW = timedelta(hours=24)
ACTION_ORDER = {"deploy": 0, "auto-rollback": 1, "rollback": 2}


def parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Entry:
    """One readable releases.log line."""

    ts: datetime
    action: str
    result: str
    commit_ts: datetime | None
    text: str

    @classmethod
    def parse(cls, line: str) -> Entry | None:
        try:
            record = json.loads(line)
        except ValueError:
            return None
        if not isinstance(record, dict):
            return None
        ts = parse_ts(record.get("ts"))
        action, result = record.get("action"), record.get("result")
        if ts is None or action not in ACTION_ORDER or not isinstance(result, str):
            return None
        return cls(ts, action, result, parse_ts(record.get("commit_ts")), json.dumps(record, sort_keys=True))

    @property
    def sort_key(self) -> tuple[datetime, int, str]:
        return (self.ts, ACTION_ORDER[self.action], self.text)

    @property
    def is_successful_deploy(self) -> bool:
        return self.action == "deploy" and self.result == "ok"

    @property
    def is_deploy_attempt(self) -> bool:
        return (
            self.is_successful_deploy
            or self.action == "auto-rollback"
            or (self.action == "deploy" and self.result == "failed")
        )

    @property
    def is_manual_rollback(self) -> bool:
        return self.action == "rollback" and self.result in ("ok", "failed")

    @property
    def restores(self) -> bool:
        return self.result == "ok"

    @property
    def lead_time(self) -> float | None:
        if self.commit_ts is None or self.commit_ts > self.ts:
            return None
        return (self.ts - self.commit_ts).total_seconds()


class History:
    """The readable lines of one window, oldest first."""

    def __init__(self, entries: Iterable[Entry]) -> None:
        self.entries = sorted(entries, key=lambda entry: entry.sort_key)

    def failure_positions(self) -> list[int]:
        failures = {i for i, entry in enumerate(self.entries) if entry.action == "auto-rollback"}
        last_deploy: int | None = None
        for i, entry in enumerate(self.entries):
            if entry.is_successful_deploy:
                last_deploy = i
            elif (
                entry.is_manual_rollback
                and last_deploy is not None
                and entry.ts - self.entries[last_deploy].ts <= MANUAL_ROLLBACK_WINDOW
            ):
                failures.add(last_deploy)
        return sorted(failures)

    def restore_seconds(self, failure: int) -> float | None:
        entry = self.entries[failure]
        if entry.action == "auto-rollback" and entry.restores:
            return 0.0
        for later in self.entries[failure + 1 :]:
            if later.restores:
                return (later.ts - entry.ts).total_seconds()
        return None

    def metrics(self) -> dict[str, Any]:
        deploys = [entry for entry in self.entries if entry.is_successful_deploy]
        lead_times = [lead for lead in (entry.lead_time for entry in deploys) if lead is not None]
        attempts = sum(1 for entry in self.entries if entry.is_deploy_attempt)
        failures = self.failure_positions()
        restores = [self.restore_seconds(failure) for failure in failures]
        restored = [seconds for seconds in restores if seconds is not None]
        return {
            "deployment_frequency": len(deploys),
            "lead_time_median_s": statistics.median(lead_times) if lead_times else None,
            "change_failures": len(failures),
            "deploy_attempts": attempts,
            "change_failure_rate": len(failures) / attempts if attempts else None,
            "time_to_restore_median_s": statistics.median(restored) if restored else None,
            "unrestored_failures": len(restores) - len(restored),
        }


def report(lines: Sequence[str], now: datetime) -> dict[str, Any]:
    entries = [Entry.parse(line) for line in lines if line.strip()]
    readable = [entry for entry in entries if entry is not None]
    recent = [entry for entry in readable if now - WINDOW <= entry.ts <= now]
    return {
        "last_30_days": History(recent).metrics(),
        "all": History(readable).metrics(),
        "ignored_lines": sum(1 for line in lines if line.strip()) - len(readable),
    }


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def render(source: str, metrics: dict[str, Any]) -> str:
    rows = [f"DORA metrics from {source} ({metrics['ignored_lines']} unreadable lines ignored)"]
    rows.append(f"{'':28}{'last 30 days':<24}all")

    def row(label: str, cell: Any) -> None:
        rows.append(f"{label:<28}{cell(metrics['last_30_days']):<24}{cell(metrics['all'])}")

    row("Deployment frequency", lambda m: f"{m['deployment_frequency']} deploys")
    row("Lead time for changes", lambda m: f"{duration(m['lead_time_median_s'])} median")
    row(
        "Change failure rate",
        lambda m: (
            "n/a"
            if m["change_failure_rate"] is None
            else f"{m['change_failure_rate']:.0%} ({m['change_failures']}/{m['deploy_attempts']})"
        ),
    )
    row(
        "Time to restore",
        lambda m: f"{duration(m['time_to_restore_median_s'])} median, {m['unrestored_failures']} unrestored",
    )
    return "\n".join(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DORA metrics from releases.log (make dora)")
    parser.add_argument("log", nargs="?", default=DEFAULT_LOG, help=f"releases.log (default {DEFAULT_LOG})")
    parser.add_argument("--json", action="store_true", help="print the metrics as JSON")
    parser.add_argument("--now", help="end of the 30-day window, UTC like 2026-11-03T08:00:00Z (default: now)")
    args = parser.parse_args(argv)
    now = parse_ts(args.now) if args.now else datetime.now(UTC)
    if now is None:
        parser.error(f"--now {args.now!r} is not a UTC time like 2026-11-03T08:00:00Z")
    try:
        with open(args.log, encoding="utf-8") as log:
            lines = log.read().splitlines()
    except OSError as error:
        print(
            f"dora: cannot read {args.log}: {error.strerror} (run make deploy or make rollback first)", file=sys.stderr
        )
        return 1
    metrics = report(lines, now)
    print(json.dumps(metrics, indent=2) if args.json else render(args.log, metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
