"""RoadMapService through its driving port `served()`; the two driven ports are faked at the boundary (D301, D314).

Universe: the served view (known, map_date, region names, total_bytes). The matching rule is the domain's
`select_served`; here we check what the service does with its answer: names the regions and the date, keeps the date of
an unknown map, and keeps the last matched map while the engine says nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.ports.region_catalogue import CatalogueEntry, CatalogueUnavailableError
from overland_planner.application.ports.road_map_changes import ChangeRequest, RequestedRegion
from overland_planner.application.ports.tileset_store import ServedRegion, TilesetListing
from overland_planner.application.roadmap.facade import ChangesUnavailableError, RoadMapService
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

    def __init__(self, open_: bool = True) -> None:
        self.open = open_
        self.request: ChangeRequest | None = None
        self.report: tuple[list[str], list[str]] | None = None

    def available(self) -> bool:
        return self.open

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
