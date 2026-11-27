"""RoadMapService through its driving port `served()`; the two driven ports are faked at the boundary (D301, D314).

Universe: the served view (known, map_date, region names, total_bytes). The matching rule is the domain's
`select_served`; here we check what the service does with its answer: names the regions and the date, keeps the date of
an unknown map, and keeps the last matched map while the engine says nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.region_catalogue import CatalogueEntry, CatalogueUnavailableError
from overland_planner.application.ports.road_map_changes import (
    STEPS,
    ChangeRequest,
    RebuildProgress,
    RebuildResult,
    RequestedRegion,
)
from overland_planner.application.ports.tileset_store import ServedRegion, TilesetListing
from overland_planner.application.roadmap.facade import SEED_REGION_KEYS, ChangesUnavailableError, RoadMapService
from overland_planner.domain.catalog.coordinate import Coordinate
from overland_planner.domain.roadmap.outline import Outline
from overland_planner.domain.roadmap.region_choice import Refusal
from overland_planner.domain.roadmap.served_map import ServedId, TilesetEntry
from tests.common.fakes import FakeClock

BORDER = Outline(rings=((Coordinate(0, 0), Coordinate(0, 1), Coordinate(1, 0)),))
GB = 10**9


class FakeServedMap:
    def __init__(self, answer: ServedId | None = None) -> None:
        self.answer = answer

    def served_id(self) -> ServedId | None:
        return self.answer

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


class FakeStore:
    def __init__(self, listing: TilesetListing, hint: str | None = None) -> None:
        self.current = listing
        self.hint = hint

    def listing(self) -> TilesetListing:
        return self.current

    def serving_hint(self) -> str | None:
        return self.hint

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


def region(key: str, size_gb: float) -> ServedRegion:
    return ServedRegion(key=key, name=key.title(), parent_name=None, bytes=int(size_gb * GB), outline=BORDER)


def listing(*maps: tuple[str, int, list[ServedRegion] | None]) -> TilesetListing:
    """(directory, epoch, regions or None for a directory with no valid record)."""
    return TilesetListing(
        entries=tuple(TilesetEntry(name, epoch, regions is not None) for name, epoch, regions in maps),
        regions={name: tuple(regions) for name, _, regions in maps if regions is not None},
        built_at={name: epoch for name, epoch, _ in maps},
    )


def view(service: RoadMapService) -> dict[str, object]:
    served = service.served()
    return {
        "known": served.known,
        "map_date": served.map_date,
        "regions": [r.name for r in served.regions],
        "total_bytes": served.total_bytes,
    }


NOV_1, NOV_27 = 1_793_534_400, 1_795_867_200
TWO_MAPS = listing(
    ("20261101", NOV_1, [region("italy", 2)]), ("20261127", NOV_27, [region("italy", 2), region("spain", 1.5)])
)


@given(epoch_of_served=st.sampled_from([NOV_1, NOV_27]))
def test_the_regions_and_the_date_of_the_directory_whose_epoch_the_engine_reports(epoch_of_served: int) -> None:
    service = RoadMapService(FakeServedMap(epoch_of_served), FakeStore(TWO_MAPS))
    expected = {
        NOV_1: ["Italy"],
        NOV_27: ["Italy", "Spain"],
    }[epoch_of_served]
    assert view(service) == {
        "known": True,
        "map_date": datetime.fromtimestamp(epoch_of_served, UTC),
        "regions": expected,
        "total_bytes": {NOV_1: 2 * GB, NOV_27: int(3.5 * GB)}[epoch_of_served],
    }


def test_a_directory_named_by_the_offline_road_map_is_served_with_its_own_date() -> None:
    service = RoadMapService(FakeServedMap("20261127"), FakeStore(TWO_MAPS))
    assert view(service)["regions"] == ["Italy", "Spain"]
    assert view(service)["map_date"] == datetime.fromtimestamp(NOV_27, UTC)


@given(epoch=st.integers(min_value=1, max_value=2_000_000_000))
def test_an_epoch_with_no_regions_is_an_unknown_map_that_still_has_its_date(epoch: int) -> None:
    # a directory without a valid record (today's map) and an epoch no directory carries are the same unknown
    store = FakeStore(listing(("20261126", 1_000, None), ("20261127", 2_000, [region("italy", 1)])))
    served_epoch = epoch if epoch not in (1_000, 2_000) else 3_000
    assert view(RoadMapService(FakeServedMap(served_epoch), store)) == {
        "known": False,
        "map_date": datetime.fromtimestamp(served_epoch, UTC),
        "regions": [],
        "total_bytes": 0,
    }
    assert view(RoadMapService(FakeServedMap(1_000), store)) == {
        "known": False,
        "map_date": datetime.fromtimestamp(1_000, UTC),
        "regions": [],
        "total_bytes": 0,
    }


def test_nothing_known_and_no_date_when_the_engine_says_nothing_and_nothing_was_seen() -> None:
    service = RoadMapService(FakeServedMap(None), FakeStore(TWO_MAPS))
    assert view(service) == {"known": False, "map_date": None, "regions": [], "total_bytes": 0}


def test_no_engine_answer_at_all_is_an_unknown_map() -> None:
    assert view(RoadMapService(None, FakeStore(TWO_MAPS)))["known"] is False


def test_the_last_matched_map_is_kept_while_the_engine_does_not_answer() -> None:
    engine = FakeServedMap(NOV_27)
    service = RoadMapService(engine, FakeStore(TWO_MAPS))
    named = view(service)
    engine.answer = None  # the build has stopped the engine
    assert view(service) == named
    engine.answer = NOV_1  # the engine is back, on the older map: that one is named again
    assert view(service)["regions"] == ["Italy"]


def test_a_restarted_planner_falls_back_to_the_tileset_the_rebuild_says_it_serves() -> None:
    service = RoadMapService(FakeServedMap(None), FakeStore(TWO_MAPS, hint="20261127"))
    assert view(service) == {
        "known": True,
        "map_date": datetime.fromtimestamp(NOV_27, UTC),
        "regions": ["Italy", "Spain"],
        "total_bytes": int(3.5 * GB),
    }


def test_a_hint_that_matches_no_directory_is_an_unknown_map() -> None:
    assert view(RoadMapService(FakeServedMap(None), FakeStore(TWO_MAPS, hint="19990101")))["known"] is False


# ------------------------------------------------------------------------------------- the catalogue (D306, D308)
def square(west: float, south: float, east: float, north: float) -> Outline:
    ring = (Coordinate(south, west), Coordinate(south, east), Coordinate(north, east), Coordinate(north, west))
    return Outline(rings=(ring,))


class FakeCatalogue:
    """The free list at its port boundary: entries, sizes and borders; records which borders were fetched."""

    def __init__(self) -> None:
        self.entries_ = (
            CatalogueEntry("europe", "Europe", None, "u", "p"),
            CatalogueEntry("italy", "Italy", "europe", "u", "p"),
            CatalogueEntry("lombardy", "Lombardy", "italy", "u", "p"),
            CatalogueEntry("spain", "Spain", "europe", "u", "p"),
            CatalogueEntry("portugal", "Portugal", "europe", "u", "p"),
            CatalogueEntry("us", "United States of America", None, "u", "p"),
            CatalogueEntry("us/utah", "Utah", "us", "u", "p"),
        )
        self.sizes: dict[str, int | None] = {
            "lombardy": GB // 2,
            "portugal": int(0.4 * GB),
            "us/utah": int(1.1 * GB),
            "europe": 30 * GB,
        }
        self.borders = {
            "portugal": square(2, 0, 3, 1),  # touches Spain
            "us/utah": square(50, 50, 51, 51),
            "europe": square(-9, -9, 9, 9),
        }
        self.fetched: list[str] = []

    def entries(self) -> tuple[CatalogueEntry, ...]:
        return self.entries_

    def size_of(self, entry: CatalogueEntry) -> int | None:
        return self.sizes.get(entry.key)

    def outline_of(self, entry: CatalogueEntry) -> Outline:
        self.fetched.append(entry.key)
        return self.borders[entry.key]

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


def served_two_regions() -> TilesetListing:
    italy = ServedRegion("italy", "Italy", "Europe", 2 * GB, square(0, 0, 1, 1))
    spain = ServedRegion("spain", "Spain", "Europe", int(1.5 * GB), square(1, 0, 2, 1))
    return listing(("20261127", NOV_27, [italy, spain]))


def planner_with(catalogue: FakeCatalogue | None) -> RoadMapService:
    return RoadMapService(FakeServedMap(NOV_27), FakeStore(served_two_regions()), catalogue)


@pytest.mark.parametrize(
    ("words", "name", "in_map"),
    [
        ("italy", "Italy", True),  # served itself
        ("lombardy", "Lombardy", True),  # covered by its served ancestor
        ("portugal", "Portugal", False),
        ("europe", "Europe", False),  # an ancestor of what is served is not itself served
    ],
)
def test_a_region_found_says_whether_the_map_already_covers_it(words: str, name: str, in_map: bool) -> None:
    hits = planner_with(FakeCatalogue()).search_catalogue(words)
    assert [(hit.name, hit.in_map) for hit in hits if hit.name == name] == [(name, in_map)]


def test_adding_a_region_summarises_figures_and_fetches_only_its_border() -> None:
    catalogue = FakeCatalogue()
    summary = planner_with(catalogue).preview_change(["italy", "spain", "portugal"])
    assert [(r.key, r.name) for r in summary.added] == [("portugal", "Portugal")]
    assert summary.removed == ()
    assert summary.total_bytes == int(3.9 * GB)  # 2 + 1.5 served, 0.4 asked of the list
    assert (summary.total_minutes, summary.pause_minutes) == (34, 23)  # D305: round(8.2 x 3.9 + 2.5), round(6 x 3.9)
    assert summary.land_groups == (("Italy", "Portugal", "Spain"),)
    assert summary.not_linked_note is None
    assert catalogue.fetched == ["portugal"]


def test_removing_a_region_names_it_and_fetches_nothing() -> None:
    catalogue = FakeCatalogue()
    summary = planner_with(catalogue).preview_change(["italy"])
    assert ([r.key for r in summary.added], [r.name for r in summary.removed]) == ([], ["Spain"])
    assert summary.total_bytes == 2 * GB
    assert catalogue.fetched == []


def test_a_region_far_from_the_others_is_a_note_and_not_a_refusal() -> None:
    summary = planner_with(FakeCatalogue()).preview_change(["italy", "spain", "us/utah"])
    assert summary.land_groups == (("Italy", "Spain"), ("Utah",))
    assert summary.not_linked_note == (
        "Utah is not linked by land to your other regions. "
        "Trips inside Utah, or inside Europe, are fine; a trip between them can't be planned."
    )


def test_a_change_that_cannot_be_summarised_says_why() -> None:
    sizeless = FakeCatalogue()
    sizeless.sizes.pop("portugal")
    with pytest.raises(CatalogueUnavailableError):
        planner_with(sizeless).preview_change(["italy", "portugal"])
    with pytest.raises(CatalogueUnavailableError):
        planner_with(None).preview_change(["italy"])
    with pytest.raises(Refusal) as unknown:
        planner_with(FakeCatalogue()).preview_change(["italy", "atlantis"])
    assert unknown.value.code == "unknown_region"
    with pytest.raises(Refusal) as overlap:
        planner_with(FakeCatalogue()).preview_change(["italy", "lombardy"])
    assert overlap.value.code == "overlaps_region"


# ------------------------------------------------------------------------------ the change queue (D303, D308, D315)
class FakeChanges:
    """The change queue at its port boundary: keeps what it is given, as the helper's folder would."""

    def __init__(self, open_: bool = True, seen: datetime | None = None) -> None:
        self.open = open_
        self.seen: datetime | None = CLOCK.now() if seen is None else seen  # the helper has just looked
        self.running_asked: ChangeRequest | None = None
        self.note: RebuildProgress | None = None
        self.request: ChangeRequest | None = None
        self.report: tuple[list[str], list[str]] | None = None
        self.taken = False
        self.ended: RebuildResult | None = None

    def waiting(self) -> bool:
        return self.request is not None

    def running(self) -> bool:
        return self.taken or self.running_asked is not None

    def available(self) -> bool:
        return self.open

    def running_request(self) -> ChangeRequest | None:
        return self.running_asked

    def progress(self) -> RebuildProgress | None:
        return self.note

    def helper_seen_at(self) -> datetime | None:
        return self.seen

    def result(self) -> RebuildResult | None:
        return self.ended

    def queue(self, request: ChangeRequest, added: object, removed: object) -> None:
        assert self.open, "the folder cannot be written"
        self.request, self.report = request, (list(added), list(removed))  # type: ignore[call-overload]

    def cancel(self) -> bool:
        waiting, self.request = self.request is not None, None
        return waiting

    def pending(self) -> ChangeRequest | None:
        return self.request

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


CLOCK = FakeClock(datetime(2026, 11, 28, 21, 0, tzinfo=UTC))
START = datetime(2026, 11, 29, 2, 0, tzinfo=UTC)


def queued_planner(
    catalogue: FakeCatalogue | None = None, changes: FakeChanges | None = None, max_gb: float = 8.0
) -> tuple[RoadMapService, FakeChanges, FakeCatalogue]:
    catalogue = catalogue or FakeCatalogue()
    changes = FakeChanges() if changes is None else changes
    service = RoadMapService(
        FakeServedMap(NOV_27), FakeStore(served_two_regions()), catalogue, changes, CLOCK, max_gb=max_gb
    )
    return service, changes, catalogue


def test_a_planned_change_keeps_the_whole_new_map_ready_and_answers_with_the_summary() -> None:
    service, changes, _ = queued_planner()
    summary = service.plan_change(["italy", "portugal"], START)
    assert changes.request == ChangeRequest(
        requested_at=CLOCK.now(),
        start_at=START,
        regions=(
            RequestedRegion("italy", "Italy", "Europe", "u", "p", 2 * GB),  # served: its size from the record
            RequestedRegion("portugal", "Portugal", "Europe", "u", "p", int(0.4 * GB)),
        ),
    )
    assert changes.report == (["Portugal"], ["Spain"])
    assert ([r.name for r in summary.added], [r.name for r in summary.removed]) == (["Portugal"], ["Spain"])
    assert summary.total_bytes == int(2.4 * GB)


def test_a_change_with_no_start_asks_for_none() -> None:
    service, changes, _ = queued_planner()
    service.plan_change(["italy", "spain", "us/utah"])
    assert changes.request is not None and changes.request.start_at is None
    assert changes.request.regions[-1] == RequestedRegion(
        "us/utah", "Utah", "United States of America", "u", "p", int(1.1 * GB)
    )


@pytest.mark.parametrize(
    ("keys", "code"),
    [
        ([], "no_regions"),
        (["italy", "atlantis"], "unknown_region"),
        (["italy", "lombardy"], "overlaps_region"),
        (["italy", "spain", "portugal", "us/utah"], "too_big"),  # 2 + 1.5 + 0.4 + 1.1 = 5 GB, limit 4
    ],
)
def test_a_change_the_rules_refuse_writes_nothing(keys: list[str], code: str) -> None:
    service, changes, _ = queued_planner(max_gb=4)
    with pytest.raises(Refusal) as refused:
        service.plan_change(keys, START)
    assert refused.value.code == code
    assert changes.request is None


def test_a_change_with_no_region_is_refused_in_plain_words_after_the_busy_checks() -> None:
    service, changes, _ = queued_planner()
    with pytest.raises(Refusal) as refused:
        service.plan_change([], START)
    assert refused.value.message == "Choose at least one region for the road map."
    service.plan_change(["italy"], START)  # one waits now: the busy refusal comes first
    with pytest.raises(Refusal) as busy:
        service.plan_change([], START)
    assert busy.value.code == "change_pending" and changes.request is not None


def test_a_change_too_big_is_refused_before_any_border_is_fetched() -> None:
    service, _, catalogue = queued_planner(max_gb=3)
    with pytest.raises(Refusal):
        service.plan_change(["italy", "spain", "portugal"], START)
    assert catalogue.fetched == []


def test_the_size_refusal_says_the_total_and_the_limit() -> None:
    service, _, _ = queued_planner(max_gb=3)
    with pytest.raises(Refusal) as refused:
        service.plan_change(["italy", "spain", "portugal"], START)
    assert "3.9 GB" in refused.value.message and "3 GB" in refused.value.message


@pytest.mark.parametrize(
    ("key", "name", "parent_key", "address"),
    [
        ("Italy", "Italy", "europe", "u"),  # a key the helper would refuse
        ("../italy", "Italy", "europe", "u"),
        ("italy", "Ita\tly", "europe", "u"),  # a tab breaks the line
        ("italy", "Ita\nly", "europe", "u"),
        ("italy", "", "europe", "u"),
        ("italy", "I" * 121, "europe", "u"),  # longer than 120 bytes
        ("italy", "\u00e0" * 61, "europe", "u"),  # 122 bytes in 61 letters
        ("italy", "Italy", "europe", "https://dl.test/../etc"),  # a path out of the download prefix
        ("italy", "Italy", "europe", "https://dl.test/a\tb"),
    ],
)
def test_a_region_the_helper_would_refuse_is_never_written(key: str, name: str, parent_key: str, address: str) -> None:
    catalogue = FakeCatalogue()
    catalogue.entries_ = (
        CatalogueEntry("europe", "Europe", None, "u", "p"),
        CatalogueEntry(key, name, parent_key, address, "p"),
    )
    catalogue.borders = {key: square(0, 0, 1, 1)}
    catalogue.sizes = {key: GB}
    changes = FakeChanges()
    service = RoadMapService(FakeServedMap(None), FakeStore(listing()), catalogue, changes, CLOCK)
    with pytest.raises(Refusal) as refused:
        service.plan_change([key], START)
    assert refused.value.code == "unknown_region"
    assert changes.request is None


def test_a_name_of_120_bytes_and_a_parent_the_helper_accepts_are_written() -> None:
    catalogue = FakeCatalogue()
    catalogue.entries_ = (
        CatalogueEntry("europe", "\u00e0" * 60, None, "u", "p"),
        CatalogueEntry("europe/x-1", "X" * 120, "europe", "u", "p"),
    )
    catalogue.borders = {"europe/x-1": square(0, 0, 1, 1)}
    catalogue.sizes = {"europe/x-1": GB}
    changes = FakeChanges()
    RoadMapService(FakeServedMap(None), FakeStore(listing()), catalogue, changes, CLOCK).plan_change(["europe/x-1"])
    assert changes.request is not None and changes.request.regions[0].parent_name == "\u00e0" * 60


def test_a_served_region_missing_from_the_list_cannot_be_written() -> None:
    service, changes, _ = queued_planner()
    catalogue = FakeCatalogue()
    catalogue.entries_ = tuple(e for e in catalogue.entries_ if e.key != "italy")
    service = RoadMapService(FakeServedMap(NOV_27), FakeStore(served_two_regions()), catalogue, changes, CLOCK)
    with pytest.raises(Refusal) as refused:
        service.plan_change(["italy", "spain"], START)
    assert refused.value.code == "unknown_region"
    assert changes.request is None


@pytest.mark.parametrize("changes", [None, FakeChanges(open_=False)])
def test_without_a_place_to_keep_changes_nothing_is_planned_and_the_service_says_so(
    changes: FakeChanges | None,
) -> None:
    service = RoadMapService(FakeServedMap(NOV_27), FakeStore(served_two_regions()), FakeCatalogue(), changes, CLOCK)
    assert service.changes_available() is False
    with pytest.raises(ChangesUnavailableError):
        service.plan_change(["italy", "portugal"], START)


def test_a_waiting_change_is_told_against_the_map_served_now_and_a_cancel_clears_it() -> None:
    service, changes, _ = queued_planner()
    assert service.changes_available() is True
    assert service.planned_change() is None
    service.plan_change(["italy", "portugal"], START)
    planned = service.planned_change()
    assert planned is not None
    assert (planned.requested_at, planned.start_at) == (CLOCK.now(), START)
    assert ([(r.key, r.name) for r in planned.added], [(r.key, r.name) for r in planned.removed]) == (
        [("portugal", "Portugal")],
        [("spain", "Spain")],
    )
    assert service.cancel_change() is True
    assert (service.planned_change(), changes.request) == (None, None)
    assert service.cancel_change() is False


def test_nothing_waits_and_nothing_is_cancelled_without_a_place_to_keep_changes() -> None:
    service = RoadMapService(FakeServedMap(NOV_27), FakeStore(served_two_regions()))
    assert (service.planned_change(), service.cancel_change()) == (None, False)


def test_a_region_containing_served_ones_is_refused_naming_every_one_of_them() -> None:
    service, changes, _ = queued_planner()
    with pytest.raises(Refusal) as refused:
        service.plan_change(["europe", "italy", "spain"], START)
    assert refused.value.message == "Europe contains Italy and Spain, which are already in the road map"
    assert changes.request is None


# ------------------------------------------------------------ one change, one rebuild a day, a start window (D305)
def test_a_second_change_is_refused_while_one_waits_or_runs_and_writes_nothing() -> None:
    service, changes, _ = queued_planner()
    service.plan_change(["italy", "portugal"], START)
    kept = changes.request
    with pytest.raises(Refusal) as pending:
        service.plan_change(["italy", "us/utah"], START)
    changes.request, changes.taken = None, True  # the helper took it
    with pytest.raises(Refusal) as running:
        service.plan_change(["italy", "us/utah"], START)
    assert (pending.value.code, running.value.code) == ("change_pending", "rebuild_running")
    assert kept is not None and changes.request is None


@pytest.mark.parametrize(
    ("start", "accepted"),
    [
        (CLOCK.now() + timedelta(minutes=1), False),
        (CLOCK.now() + timedelta(minutes=2), True),
        (CLOCK.now() + timedelta(days=14), True),
        (CLOCK.now() + timedelta(days=14, seconds=1), False),
    ],
)
def test_a_start_is_kept_only_from_two_minutes_to_fourteen_days_ahead(start: datetime, accepted: bool) -> None:
    service, changes, _ = queued_planner()
    if accepted:
        service.plan_change(["italy", "portugal"], start)
        assert changes.request is not None and changes.request.start_at == start
    else:
        with pytest.raises(Refusal) as refused:
            service.plan_change(["italy", "portugal"], start)
        assert (refused.value.code, changes.request) == ("bad_start", None)


def day_service(*directories: str) -> tuple[RoadMapService, FakeChanges]:
    maps = [(name, NOV_27, [region("italy", 2)]) for name in directories]
    changes = FakeChanges()
    service = RoadMapService(
        FakeServedMap("20261127"), FakeStore(listing(*maps)), FakeCatalogue(), changes, CLOCK, max_gb=8
    )
    return service, changes


@pytest.mark.parametrize(
    ("directories", "start", "refused_from"),
    [
        (["20261127"], None, None),  # a start now is the 28th UTC: only the 27th has a map
        (["20261127", "20261128"], None, datetime(2026, 11, 29, tzinfo=UTC)),  # a leftover of a failed switch
        (["20261127", "20261129"], START, datetime(2026, 11, 30, tzinfo=UTC)),
        (["20261127"], datetime(2026, 11, 29, 0, 30, tzinfo=timezone(timedelta(hours=1))), None),  # 28th UTC: free
    ],
)
def test_one_rebuild_a_utc_day_counted_by_the_directories_of_the_volume(
    directories: list[str], start: datetime | None, refused_from: datetime | None
) -> None:
    service, changes = day_service(*directories)
    if refused_from is None:
        service.plan_change(["italy", "portugal"], start)
        assert changes.request is not None
        return
    with pytest.raises(Refusal) as refused:
        service.plan_change(["italy", "portugal"], start)
    assert (refused.value.code, refused.value.details, changes.request) == (
        "same_day",
        {"next_rebuild_from": refused_from},
        None,
    )


# ------------------------------------------------------------------------- Refresh map data (D315)
def test_refresh_asks_for_the_served_regions_through_preview_and_plan() -> None:
    service, changes, _ = queued_planner()
    by_hand = service.preview_change(["italy", "spain"])
    assert service.preview_change(None) == by_hand
    assert service.plan_change(None, START) == by_hand
    assert changes.request is not None and [r.key for r in changes.request.regions] == ["italy", "spain"]


def test_refresh_with_no_record_asks_for_the_seed_regions() -> None:
    catalogue = FakeCatalogue()
    catalogue.entries_ = tuple(CatalogueEntry(key, key.title(), None, "u", "p") for key in SEED_REGION_KEYS)
    catalogue.sizes = {key: GB // 10 for key in SEED_REGION_KEYS}
    catalogue.borders = {key: square(i * 3, 0, i * 3 + 1, 1) for i, key in enumerate(SEED_REGION_KEYS)}
    changes = FakeChanges()
    service = RoadMapService(FakeServedMap(None), FakeStore(listing()), catalogue, changes, CLOCK)
    summary = service.plan_change(None, START)
    assert sorted(r.key for r in summary.added) == sorted(SEED_REGION_KEYS)
    assert changes.request is not None and sorted(r.key for r in changes.request.regions) == sorted(SEED_REGION_KEYS)


# ------------------------------------------------------------------ the helper's heartbeat and the pause (D303, D315)
@given(age_seconds=st.integers(min_value=0, max_value=1200))
def test_rebuilds_are_set_up_while_the_helper_looked_under_five_minutes_ago(age_seconds: int) -> None:
    changes = FakeChanges(seen=CLOCK.now() - timedelta(seconds=age_seconds))
    service, _, _ = queued_planner(changes=changes)
    assert service.rebuilds_set_up() is (age_seconds < 300)
    assert service.helper_seen_at() == changes.seen
    if age_seconds < 300:
        service.plan_change(["italy", "portugal"], START)
        assert changes.request is not None
    else:
        with pytest.raises(Refusal) as refused:
            service.plan_change(["italy", "portugal"], START)
        assert refused.value.code == "rebuilds_not_set_up" and "not set up" in refused.value.message
        assert changes.request is None


def test_without_a_mark_of_the_helper_nothing_is_planned() -> None:
    changes = FakeChanges()
    changes.seen = None
    service, _, _ = queued_planner(changes=changes)
    assert (service.rebuilds_set_up(), service.helper_seen_at()) == (False, None)
    with pytest.raises(Refusal) as refused:
        service.plan_change(["italy", "portugal"], START)
    assert refused.value.code == "rebuilds_not_set_up" and changes.request is None


def test_a_waiting_change_stays_planned_when_the_helper_has_not_looked_for_minutes() -> None:
    service, changes, _ = queued_planner()
    service.plan_change(["italy", "portugal"], START)
    changes.seen = CLOCK.now() - timedelta(minutes=10)
    planned = service.planned_change()
    assert planned is not None and planned.state == "planned"
    assert service.rebuilds_set_up() is False and service.helper_seen_at() == changes.seen


BUILD_START = datetime(2026, 11, 29, 3, 10, tzinfo=UTC)


def running_planner(
    step: str | None, step_at: datetime = BUILD_START, build_started_at: datetime | None = None
) -> RoadMapService:
    changes = FakeChanges()
    changes.running_asked = ChangeRequest(
        requested_at=CLOCK.now(),
        start_at=None,
        regions=(
            RequestedRegion("italy", "Italy", "Europe", "u", "p", 2 * GB),
            RequestedRegion("portugal", "Portugal", "Europe", "u", "p", 3 * GB),
        ),
    )
    changes.note = None if step is None else RebuildProgress(step, step_at, build_started_at)
    service, _, _ = queued_planner(changes=changes)
    return service


@given(step=st.sampled_from(STEPS), minutes=st.integers(min_value=0, max_value=600))
def test_planning_is_paused_from_the_build_to_the_end_of_the_switch_and_back_after_the_estimate(
    step: str, minutes: int
) -> None:
    started = BUILD_START + timedelta(minutes=minutes)
    change = running_planner(step, started).planned_change()
    assert change is not None and (change.state, change.step) == ("running", step)
    assert change.steps_done == STEPS.index(step)
    assert change.planning_paused is (step in ("building", "switching"))
    # 5 GB to build: the pause is round(6 x 5) = 30 minutes counted from the step's own start
    assert change.planning_back_at == (started + timedelta(minutes=30) if change.planning_paused else None)
    assert [r.name for r in change.added] == ["Portugal"]


@given(later=st.integers(min_value=1, max_value=120))
def test_planning_is_back_after_the_estimate_counted_from_the_start_of_the_build_not_of_the_switch(later: int) -> None:
    switching_at = BUILD_START + timedelta(minutes=later)
    change = running_planner("switching", switching_at, build_started_at=BUILD_START).planned_change()
    assert change is not None and change.planning_paused
    assert change.planning_back_at == BUILD_START + timedelta(minutes=30)


def test_a_rebuild_that_says_nothing_about_its_step_is_running_and_pauses_nothing() -> None:
    change = running_planner(None).planned_change()
    assert change is not None
    assert (change.state, change.step, change.steps_done, change.planning_paused, change.planning_back_at) == (
        "running",
        None,
        0,
        False,
        None,
    )


# ------------------------------------------------------------------------------ how a rebuild ended (D303, D304)
ENDED = datetime(2026, 11, 29, 2, 56, tzinfo=UTC)
ASKED = ChangeRequest(
    requested_at=CLOCK.now(),
    start_at=None,
    regions=(
        RequestedRegion("italy", "Italy", "Europe", "u", "p", 2 * GB),
        RequestedRegion("spain", "Spain", "Europe", "u", "p", int(1.5 * GB)),
        RequestedRegion("portugal", "Portugal", "Europe", "u", "p", 3 * GB),
    ),
)
NOV_29 = NOV_27 + 2 * 86_400


def ended_planner(result: RebuildResult | None, engine: ServedId = NOV_27) -> RoadMapService:
    changes = FakeChanges()
    changes.ended = result
    portugal = ServedRegion("portugal", "Portugal", "Europe", 3 * GB, square(2, 0, 3, 1))
    two = served_two_regions()
    maps = listing(
        ("20261127", NOV_27, list(two.regions["20261127"])),
        ("20261129", NOV_29, [*two.regions["20261127"], portugal]),
    )
    return RoadMapService(FakeServedMap(engine), FakeStore(maps), FakeCatalogue(), changes, CLOCK)


@given(free=st.integers(min_value=0, max_value=999), need=st.integers(min_value=0, max_value=999))
def test_a_rebuild_that_stopped_for_lack_of_space_says_so_with_the_numbers_and_the_served_map_stays(
    free: int, need: int
) -> None:
    failed = RebuildResult("failed", ENDED, code="disk", free_gb=free, need_gb=need, request=ASKED, added=("Portugal",))
    service = ended_planner(failed)
    change = service.planned_change()
    assert change is not None and change.result is not None
    assert (change.state, change.result.code, change.result.finished_at) == ("failed", "disk", ENDED)
    assert f"the Pi has {free} GB of free disk and needs {need} GB" in change.result.message
    assert "map data 28 November 2026" in change.result.message  # NOV_27 is noon of the 28th
    assert "Your change is kept" in change.result.message
    assert [r.name for r in change.added] == ["Portugal"] and change.removed == ()
    assert [r.name for r in service.served().regions] == ["Italy", "Spain"]


def test_a_failure_with_a_code_nobody_knows_is_a_generic_failure_with_no_code() -> None:
    change = ended_planner(RebuildResult("failed", ENDED, code="mystery_box", request=ASKED)).planned_change()
    assert change is not None and change.result is not None
    assert change.result.code is None and "mystery_box" not in change.result.message


def test_a_failure_whose_request_cannot_be_read_does_not_promise_the_change_is_kept() -> None:
    change = ended_planner(RebuildResult("failed", ENDED, code="build")).planned_change()
    assert change is not None and change.result is not None
    assert "Your change is kept" not in change.result.message and change.added == ()


def test_a_rebuild_that_ended_well_shows_once_the_engine_serves_the_new_map() -> None:
    done = RebuildResult("done", ENDED, tileset="20261129", request=ASKED, added=("Portugal",))
    service = ended_planner(done, engine=NOV_29)
    change = service.planned_change()
    assert change is not None and change.result is not None and change.state == "done"
    assert change.result.code is None and change.result.finished_at == ENDED
    assert change.result.message.endswith("Portugal added; 3 regions, map data 30 November 2026.")
    assert [r.name for r in service.served().regions] == ["Italy", "Spain", "Portugal"]


def test_a_rebuild_that_ended_well_says_nothing_while_the_old_map_is_still_served() -> None:
    done = RebuildResult("done", ENDED, tileset="20261129", request=ASKED)
    assert ended_planner(done, engine=NOV_27).planned_change() is None


def test_a_change_waiting_or_running_hides_the_result_of_the_one_before() -> None:
    service, changes, _ = queued_planner()
    changes.ended = RebuildResult("failed", ENDED, code="disk", request=ASKED)
    service.plan_change(["italy", "portugal"], START)
    planned = service.planned_change()
    assert planned is not None and (planned.state, planned.result) == ("planned", None)


def test_the_land_groups_of_a_served_map_are_computed_once_however_often_it_is_read(monkeypatch) -> None:
    """The served map is immutable while served: reading it again (every coverage request) recomputes nothing."""
    calls: list[int] = []
    touches = Outline.touches
    monkeypatch.setattr(Outline, "touches", lambda self, other: calls.append(1) or touches(self, other))
    service = RoadMapService(FakeServedMap("20261127"), FakeStore(TWO_MAPS))

    first = service.served().coverage.land_groups()
    computed = len(calls)
    second = service.served().coverage.land_groups()

    assert computed > 0
    assert len(calls) == computed
    assert second == first
