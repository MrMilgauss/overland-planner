"""Migration policy (brief §7 step 3, D129, ADR-018): the stored revision decides refuse / copy-then-upgrade / upgrade /
nothing, and the pre-migration copies keep only the newest three.

Driving ports: `RevisionChain.action_for(stored)` and `PreMigrationCopies.name_for / to_prune` (pure policy functions).
Test Budget: 2 behaviors (decision table, copy retention) x 2 = 4; 2 property tests used.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.platform.facade import MigrationAction, PreMigrationCopies, RevisionChain
from tests.common.state_delta import assert_state_delta, set_to, unchanged

revision_ids = st.text(alphabet="0123456789abcdef-", min_size=1, max_size=12)
chains = st.lists(revision_ids, min_size=1, max_size=6, unique=True)

# How the stored revision relates to the chain -> what start-up must do (D129).
EXPECTED_ACTION = {
    "fresh": MigrationAction.UPGRADE,
    "at_head": MigrationAction.NOTHING,
    "older": MigrationAction.COPY_THEN_UPGRADE,
    "unknown": MigrationAction.REFUSE_NEWER,
}


@st.composite
def chain_and_stored_revision(draw: st.DrawFn) -> tuple[list[str], str | None, str]:
    relation = draw(st.sampled_from(sorted(EXPECTED_ACTION)))
    if relation == "older":
        chain = draw(st.lists(revision_ids, min_size=2, max_size=6, unique=True))
        return chain, draw(st.sampled_from(chain[:-1])), relation
    chain = draw(chains)
    stored = {"fresh": None, "at_head": chain[-1]}.get(relation)
    if relation == "unknown":
        stored = draw(revision_ids.filter(lambda revision: revision not in chain))
    return chain, stored, relation


@given(case=chain_and_stored_revision())
def test_the_stored_revision_decides_what_start_up_does(case: tuple[list[str], str | None, str]) -> None:
    revisions, stored, relation = case
    chain = RevisionChain.of(revisions)

    before = {"chain": chain.revisions, "action": None}
    after = {"chain": chain.revisions, "action": chain.action_for(stored)}

    assert_state_delta(
        before,
        after,
        {"chain", "action"},
        {"chain": unchanged(), "action": set_to(EXPECTED_ACTION[relation])},
        strict=True,
    )


EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
copy_times = st.lists(
    st.integers(min_value=0, max_value=10**12).map(lambda micros: EPOCH + timedelta(microseconds=micros)),
    max_size=8,
    unique=True,
)
foreign_files = st.lists(st.sampled_from(["notes.txt", "planner.sqlite", "planner-0001.sqlite"]), unique=True)


def _folder(names: set[str], foreign: set[str]) -> dict[str, Any]:
    return {"copies": frozenset(names), "foreign": frozenset(foreign)}


@given(times=copy_times, revisions=st.data(), foreign=foreign_files)
def test_only_the_newest_three_pre_migration_copies_are_kept(
    times: list[datetime], revisions: st.DataObject, foreign: list[str]
) -> None:
    named = {time: PreMigrationCopies.name_for(revisions.draw(revision_ids), time) for time in times}
    newest_three = {named[time] for time in sorted(times)[-3:]}

    before = _folder(set(named.values()), set(foreign))
    pruned = PreMigrationCopies.to_prune([*named.values(), *foreign])
    after = _folder(set(named.values()) - pruned, set(foreign) - pruned)

    assert_state_delta(
        before,
        after,
        {"copies", "foreign"},
        {"copies": set_to(frozenset(newest_three)), "foreign": unchanged()},
        strict=True,
    )
