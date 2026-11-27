"""RegionChoice and the change rules (D305, D315): overlap both ways, size, added/removed, same day, start window.

Driving port: the pure RegionChoice and check functions. Test Budget: 8 behaviors x 2 = 16; 11 used.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.roadmap.outline import Outline
from overland_planner.domain.roadmap.region_choice import (
    CatalogRegion,
    Refusal,
    RegionChoice,
    check_same_day,
    check_start_window,
)

GB = 1_000_000_000


@st.composite
def catalogues(draw):
    n = draw(st.integers(2, 7))
    regions = {}
    for i in range(n):
        parent = draw(st.sampled_from([None, *[f"r{j}" for j in range(i)]]))
        regions[f"r{i}"] = CatalogRegion(f"r{i}", f"Region {i}", parent, draw(st.integers(1, 3 * GB)))
    return regions


def ancestors(catalogue, key):
    found = []
    while (key := catalogue[key].parent) is not None:
        found.append(key)
    return found


def empty(catalogue, served=frozenset()):
    return RegionChoice(catalogue, frozenset(served), frozenset(served))


@given(catalogue=catalogues(), data=st.data())
def test_an_ancestor_and_a_descendant_are_refused_in_either_order(catalogue, data):
    pairs = [(a, k) for k in catalogue for a in ancestors(catalogue, k)]
    if not pairs:
        return
    ancestor, descendant = data.draw(st.sampled_from(pairs))
    names = (catalogue[ancestor].name, catalogue[descendant].name)
    for first, second in ((ancestor, descendant), (descendant, ancestor)):
        with pytest.raises(Refusal) as refused:
            empty(catalogue).add(first).add(second)
        assert refused.value.code == "overlaps_region"
        assert all(name in refused.value.message for name in names)


def test_the_refusal_reads_as_the_owner_approved_text():  # bypass: verbatim screen text, one example
    catalogue = {
        "us": CatalogRegion("us", "United States of America", None, 1),
        "us/utah": CatalogRegion("us/utah", "Utah", "us", 1),
    }
    with pytest.raises(Refusal) as down:
        empty(catalogue).add("us").add("us/utah")
    assert down.value.message == "Utah is already in the road map as part of United States of America"
    with pytest.raises(Refusal) as up:
        empty(catalogue).add("us/utah").add("us")
    assert up.value.message == "United States of America contains Utah, which is already in the road map"


@given(catalogue=catalogues(), data=st.data())
def test_unrelated_regions_are_accepted_and_their_bytes_add_up(catalogue, data):
    keys = list(catalogue)
    picked: list[str] = []
    for key in data.draw(st.permutations(keys)):
        related = [p for p in picked if p in ancestors(catalogue, key) or key in ancestors(catalogue, p)]
        if not related:
            picked.append(key)
    choice = empty(catalogue)
    for key in picked:
        choice = choice.add(key)
    assert choice.chosen == frozenset(picked)
    assert choice.total_bytes == sum(catalogue[k].bytes for k in picked)


@given(catalogue=catalogues(), data=st.data())
def test_added_and_removed_are_the_differences_against_the_served_keys(catalogue, data):
    keys = sorted(catalogue)
    flat = [k for k in keys if catalogue[k].parent is None]
    served = frozenset(data.draw(st.sets(st.sampled_from(flat))))
    choice = empty(catalogue, served)
    target = data.draw(st.sampled_from(flat))
    after = RegionChoice(catalogue, served, served - {target}) if target in served else choice.add(target)
    assert after.added == after.chosen - served
    assert after.removed == served - after.chosen
    assert (after.added, after.removed) == (
        (frozenset(), frozenset({target})) if target in served else (frozenset({target}), frozenset())
    )


def test_an_unknown_key_is_refused():  # bypass: single refusal code
    with pytest.raises(Refusal) as refused:
        empty({}).add("nowhere")
    assert refused.value.code == "unknown_region"


@given(extra=st.integers(0, 3 * GB), limit=st.integers(1, 20))
def test_size_above_the_limit_is_refused_with_total_and_limit(extra, limit):
    catalogue = {"big": CatalogRegion("big", "Big", None, limit * GB + extra)}
    choice = empty(catalogue).add("big")
    if extra == 0:
        choice.check_size(limit)
        return
    with pytest.raises(Refusal) as refused:
        choice.check_size(limit)
    assert refused.value.code == "too_big"
    assert f"{(limit * GB + extra) / GB:.1f} GB" in refused.value.message
    assert f"{limit} GB" in refused.value.message


def test_todays_eight_regions_pass_the_default_limit():  # bypass: the 6.4 GB figure of D305
    catalogue = {f"r{i}": CatalogRegion(f"r{i}", f"R{i}", None, 800_000_000) for i in range(8)}
    choice = empty(catalogue, catalogue)
    choice.check_size(8)
    assert (choice.estimate().total_minutes, choice.estimate().pause_minutes) == (55, 38)


def box(x0: int, size: int = 2) -> Outline:
    pts = [(x0, 0), (x0 + size, 0), (x0 + size, size), (x0, size)]
    return Outline(rings=(tuple(Coordinate(latitude=y, longitude=x) for x, y in pts),))


def test_land_groups_are_those_of_the_chosen_regions_only():  # bypass: composition of RoadMapCoverage
    catalogue = {k: CatalogRegion(k, k, None, 1) for k in ("a", "b", "c", "d")}
    outlines = {"a": box(0), "b": box(2), "c": box(20), "d": box(2)}
    choice = empty(catalogue).add("a").add("b").add("c")
    assert choice.land_groups(outlines) == (("a", "b"), ("c",))


NOW = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
TWO_MIN, FOURTEEN_DAYS = 120, 14 * 86400


@given(
    offset=st.one_of(
        st.sampled_from([TWO_MIN - 1, TWO_MIN, TWO_MIN + 1, FOURTEEN_DAYS - 1, FOURTEEN_DAYS, FOURTEEN_DAYS + 1]),
        st.integers(-100, FOURTEEN_DAYS + 100),
    )
)
def test_the_start_window_runs_from_two_minutes_to_fourteen_days(offset):
    start = NOW + timedelta(seconds=offset)
    if TWO_MIN <= offset <= FOURTEEN_DAYS:
        check_start_window(start, NOW)
    else:
        with pytest.raises(Refusal) as refused:
            check_start_window(start, NOW)
        assert refused.value.code == "bad_start"


@given(
    start=st.datetimes(
        datetime(2026, 1, 2),
        datetime(2027, 12, 30),
        timezones=st.sampled_from([UTC, timezone(timedelta(hours=11)), timezone(timedelta(hours=-9))]),
    ),
    shift=st.integers(-2, 2),
)
def test_a_start_on_the_date_of_any_directory_is_refused_until_the_next_utc_midnight(start, shift):
    day = start.astimezone(UTC).date()
    names = [(day + timedelta(days=shift)).strftime("%Y%m%d"), "20250101"]
    if shift != 0:
        check_same_day(start, names)
        return
    with pytest.raises(Refusal) as refused:
        check_same_day(start, names)
    assert refused.value.code == "same_day"
    assert refused.value.details["next_rebuild_from"] == datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(
        days=1
    )
