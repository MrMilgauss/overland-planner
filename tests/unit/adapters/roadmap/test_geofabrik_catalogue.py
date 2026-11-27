"""The Geofabrik catalogue adapter against real HTTP on a loopback port (D306, D310, D315): the list kept on disk for a
week, the size of a region asked once, what is never offered, and the probe's fault catalogue. One contract test
replays the recorded real index (trimmed) with respx."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from overland_planner.adapters.roadmap.geofabrik_catalogue import GeofabrikCatalogue
from overland_planner.application.ports.region_catalogue import CatalogueEntry, CatalogueUnavailableError
from tests.acceptance.overland_route_planner_mvp.steps.road_map_fakes import (
    GB,
    SIZES_GB,
    RecordingServer,
    Seen,
    catalogue_features,
    region_service,
)
from tests.common.fakes import FakeClock

USER_AGENT = "overland-planner/test (household trip planner)"
WEEK = timedelta(days=7)


@pytest.fixture
def server() -> Iterator[RecordingServer]:
    running = region_service()
    yield running
    running.stop()


def catalogue(server_url: str, folder: Path, clock: FakeClock, *, minimum: int = 10) -> GeofabrikCatalogue:
    return GeofabrikCatalogue(
        f"{server_url}/index-v1-nogeom.json", folder, clock, user_agent=USER_AGENT, min_features=minimum
    )


def serving(text: str | Callable[[str], str], status: int = 200) -> RecordingServer:
    """A service whose every answer is `text` (or what `text` makes of the service's own address)."""
    holder: dict[str, RecordingServer] = {}

    def respond(seen: Seen) -> tuple[int, dict[str, str], bytes]:
        body = text if isinstance(text, str) else text(holder["server"].url)
        return status, {}, body.encode()

    holder["server"] = RecordingServer(respond).start()
    return holder["server"]


def feature(key: str, base: str, parent: str | None = None, **urls: str | None) -> dict[str, Any]:
    addresses = {"pbf": f"{base}/{key}-latest.osm.pbf", "poly": f"{base}/{key}.poly"} | urls
    return {
        "type": "Feature",
        "properties": {
            "id": key,
            "name": key.title(),
            "parent": parent,
            "urls": {name: value for name, value in addresses.items() if value is not None},
        },
    }


def index_of(*features: dict[str, Any]) -> str:
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


def keys(found: Any) -> list[str]:
    return [entry.key for entry in found]


def test_the_list_is_fetched_once_with_the_planners_name_and_no_query(server: RecordingServer, tmp_path: Path) -> None:
    clock = FakeClock()
    found = catalogue(server.url, tmp_path, clock)
    first, second = found.entries(), found.entries()
    asked = server.requests("GET", "index-v1")
    assert first == second and len(first) == len(catalogue_features())
    assert [(a.query, a.headers["user-agent"]) for a in asked] == [({}, USER_AGENT)]
    utah = next(entry for entry in first if entry.key == "us/utah")
    assert (utah.name, utah.parent) == ("Utah", "us")
    assert utah.pbf_url == f"{server.url}/north-america/us/utah/utah-latest.osm.pbf"
    assert utah.poly_url == f"{server.url}/north-america/us/utah/utah.poly"


def test_the_kept_list_serves_a_restart_and_is_fetched_again_after_a_week(
    server: RecordingServer, tmp_path: Path
) -> None:
    clock = FakeClock()
    catalogue(server.url, tmp_path, clock).entries()
    catalogue(server.url, tmp_path, clock).entries()  # a restarted planner
    assert len(server.requests("GET", "index-v1")) == 1
    clock.advance(WEEK.total_seconds() - 1)
    catalogue(server.url, tmp_path, clock).entries()
    assert len(server.requests("GET", "index-v1")) == 1
    clock.advance(2)
    catalogue(server.url, tmp_path, clock).entries()
    assert len(server.requests("GET", "index-v1")) == 2


def test_the_stale_copy_is_used_when_the_service_does_not_answer(server: RecordingServer, tmp_path: Path) -> None:
    clock = FakeClock()
    kept = catalogue(server.url, tmp_path, clock).entries()
    server.stop()
    clock.advance(8 * 86_400)
    assert catalogue(server.url, tmp_path, clock).entries() == kept


@pytest.mark.parametrize(
    "service",
    [
        pytest.param(lambda: serving("{"), id="truncated"),
        pytest.param(lambda: serving("not found", status=404), id="not found"),
        pytest.param(lambda: serving(index_of()), id="no feature at all"),
    ],
)
def test_without_a_kept_copy_a_list_that_does_not_come_is_unavailable(
    service: Callable[[], RecordingServer], tmp_path: Path
) -> None:
    broken = service()
    with pytest.raises(CatalogueUnavailableError):
        catalogue(broken.url, tmp_path, FakeClock(), minimum=1).entries()
    broken.stop()
    gone = catalogue(broken.url, tmp_path, FakeClock())
    with pytest.raises(CatalogueUnavailableError):
        gone.entries()


def test_a_corrupt_kept_copy_is_discarded_and_the_list_fetched(server: RecordingServer, tmp_path: Path) -> None:
    clock = FakeClock()
    catalogue(server.url, tmp_path, clock).entries()
    (kept,) = [path for path in tmp_path.rglob("*") if path.is_file()]
    kept.write_text("{ this is not the list", encoding="utf-8")
    assert len(catalogue(server.url, tmp_path, clock).entries()) == len(catalogue_features())
    assert len(server.requests("GET", "index-v1")) == 2


def test_what_cannot_be_offered_is_left_out(tmp_path: Path) -> None:
    service = serving(
        lambda base: index_of(
            feature("fine", base),
            feature("child", base, parent="fine"),
            feature("no-pbf", base, pbf=None),
            feature("no-poly", base, poly=None),
            feature("orphan", base, parent="missing"),
            feature("grandchild", base, parent="orphan"),
            feature("stranger", "http://elsewhere.example"),
        )
    )
    offered = catalogue(service.url, tmp_path, FakeClock()).entries()
    assert sorted(keys(offered)) == ["child", "fine"]
    service.stop()


def test_the_size_of_a_region_is_asked_by_one_head_and_remembered_for_a_week(
    server: RecordingServer, tmp_path: Path
) -> None:
    clock = FakeClock()
    found = catalogue(server.url, tmp_path, clock)
    utah = next(entry for entry in found.entries() if entry.key == "us/utah")
    assert found.size_of(utah) == int(SIZES_GB["us/utah"] * GB) == found.size_of(utah)
    (asked,) = server.requests("HEAD", "-latest.osm.pbf")
    assert (asked.path, asked.query, asked.headers["user-agent"]) == (
        "/north-america/us/utah/utah-latest.osm.pbf",
        {},
        USER_AGENT,
    )
    clock.advance(WEEK.total_seconds() + 1)
    found.size_of(utah)
    assert len(server.requests("HEAD", "-latest.osm.pbf")) == 2


def test_a_size_the_service_cannot_give_is_not_remembered(tmp_path: Path) -> None:
    holder: dict[str, RecordingServer] = {}

    def respond(seen: Seen) -> tuple[int, dict[str, str], bytes]:
        if seen.method == "HEAD":
            return 404, {}, b""
        return 200, {}, index_of(feature("fine", holder["server"].url)).encode()

    holder["server"] = service = RecordingServer(respond).start()
    found = catalogue(service.url, tmp_path, FakeClock(), minimum=1)
    (fine,) = found.entries()
    assert found.size_of(fine) is None and found.size_of(fine) is None
    assert len(service.requests("HEAD")) == 2
    service.stop()


def many(base: str, count: int = 12) -> str:
    return index_of(*(feature(f"region-{n:02d}", base) for n in range(count)))


@pytest.mark.parametrize(
    ("index", "minimum", "fault"),
    [
        pytest.param(many, 5, None, id="a good list"),
        pytest.param(many, 13, "fewer", id="fewer features than expected"),
        pytest.param(lambda base: many(base)[:-30], 5, "list", id="truncated"),
        pytest.param(lambda base: many(base).replace("region-03", "region-02"), 5, "duplicate", id="duplicate key"),
        pytest.param(
            lambda base: index_of(feature("one", base), feature("two", "http://elsewhere.example")),
            1,
            "address",
            id="an address off the origin",
        ),
        pytest.param(
            lambda base: index_of(feature("one", base, parent="nobody"), feature("two", base)),
            1,
            "parent",
            id="a parent that does not resolve",
        ),
    ],
)
def test_the_probe_names_what_is_wrong_with_the_list(
    tmp_path: Path, index: Callable[[str], str], minimum: int, fault: str | None
) -> None:
    service = serving(index)
    result = catalogue(service.url, tmp_path, FakeClock(), minimum=minimum).probe()
    service.stop()
    if fault is None:
        assert (result.outcome, result.reason) == ("ok", None)
    else:
        assert (result.outcome, result.reason) == ("degraded-healthy", "region_catalogue_unavailable")
    assert len(service.requests()) == 1


def test_the_probe_reports_an_unreachable_service_and_uses_a_kept_copy(server: RecordingServer, tmp_path: Path) -> None:
    clock = FakeClock()
    assert catalogue(server.url, tmp_path, clock).probe().outcome == "ok"
    server.stop()
    assert catalogue(server.url, tmp_path, clock).probe().outcome == "ok"
    elsewhere = tmp_path / "nothing-kept"
    assert catalogue(server.url, elsewhere, clock).probe().reason == "region_catalogue_unavailable"


def test_the_planner_asks_for_100_regions_unless_told_otherwise(server: RecordingServer, tmp_path: Path) -> None:
    found = GeofabrikCatalogue(f"{server.url}/index-v1-nogeom.json", tmp_path, FakeClock(), user_agent=USER_AGENT)
    assert found.probe().reason == "region_catalogue_unavailable"  # the trimmed list has 19


def test_contract_the_recorded_real_index_is_read_as_the_planner_expects(tmp_path: Path) -> None:
    recorded = (
        Path(__file__).resolve().parents[3]
        / "acceptance/overland_route_planner_mvp/fixtures/road-map/geofabrik-index-trimmed.json"
    )
    address = "https://download.geofabrik.de/index-v1-nogeom.json"
    with respx.mock(assert_all_called=True) as mock:
        mock.get(address).mock(return_value=httpx.Response(200, text=recorded.read_text(encoding="utf-8")))
        found = GeofabrikCatalogue(address, tmp_path, FakeClock(), user_agent=USER_AGENT, min_features=19)
        assert found.probe().outcome == "ok"
        offered = {entry.key: entry for entry in found.entries()}
    assert len(offered) == 19 and len(set(offered)) == 19
    assert all(e.pbf_url.startswith("https://download.geofabrik.de/") for e in offered.values())
    assert all(e.parent is None or e.parent in offered for e in offered.values())
    assert offered["us/georgia"].parent == "us" and offered["georgia"].parent == "europe"


# --------------------------------------------------------------------------------------------- the border of a region
def entry_of(found: GeofabrikCatalogue, key: str) -> Any:
    return next(entry for entry in found.entries() if entry.key == key)


def redirecting(routes: dict[str, tuple[int, dict[str, str], bytes]]) -> RecordingServer:
    """A service answering every path from `routes` (a missing path is 404); `{base}` in a header is its own address."""
    holder: dict[str, RecordingServer] = {}

    def respond(seen: Seen) -> tuple[int, dict[str, str], bytes]:
        status, headers, body = routes.get(seen.path, (404, {}, b"not found"))
        return status, {k: v.replace("{base}", holder["server"].url) for k, v in headers.items()}, body

    holder["server"] = RecordingServer(respond).start()
    return holder["server"]


def asked_of(service: RecordingServer, tmp_path: Path) -> Callable[[str, str], tuple[int | None, Any]]:
    """Asks the catalogue for the size of a region whose `.osm.pbf` is at the given path of `service`."""
    found = catalogue(service.url, tmp_path, FakeClock(), minimum=1)
    count = iter(range(1000))

    def ask(pbf_path: str, poly_path: str) -> tuple[int | None, Any]:
        entry = CatalogueEntry(f"r{next(count)}", "R", None, service.url + pbf_path, service.url + poly_path)
        return found.size_of(entry), entry

    return ask


def test_a_size_follows_redirects_within_the_lists_own_origin(tmp_path: Path) -> None:
    chain = redirecting(
        {
            "/italy-latest.osm.pbf": (307, {"Location": "/italy-261126.osm.pbf"}, b""),
            "/italy-261126.osm.pbf": (200, {"X-Length": "2256145962"}, b""),
            "/a-latest.osm.pbf": (301, {"Location": "{base}/b.osm.pbf"}, b""),
            "/b.osm.pbf": (307, {"Location": "/c.osm.pbf"}, b""),
            "/c.osm.pbf": (200, {"X-Length": "42"}, b""),
        }
    )
    ask = asked_of(chain, tmp_path)
    assert ask("/italy-latest.osm.pbf", "")[0] == 2256145962
    assert ask("/a-latest.osm.pbf", "")[0] == 42
    chain.stop()


def test_a_size_behind_a_redirect_off_the_origin_or_too_long_is_unknown_and_nothing_foreign_is_asked(
    tmp_path: Path,
) -> None:
    foreign = redirecting({"/x.osm.pbf": (200, {"X-Length": "7"}, b"")})
    hops = {f"/h{n}": (307, {"Location": f"/h{n + 1}"}, b"") for n in range(1, 5)}
    hops["/h5"] = (200, {"X-Length": "9"}, b"")
    service = redirecting(
        {
            "/away-latest.osm.pbf": (307, {"Location": f"{foreign.url}/x.osm.pbf"}, b""),
            "/loop-latest.osm.pbf": (307, {"Location": "/loop-latest.osm.pbf"}, b""),
            "/h0": (307, {"Location": "/h1"}, b""),
        }
        | hops
    )
    ask = asked_of(service, tmp_path)
    for name in ("away-latest.osm.pbf", "loop-latest.osm.pbf", "h0"):  # h0 -> h5 is 5 hops
        assert ask(f"/{name}", "")[0] is None
    assert foreign.requests() == []
    service.stop()
    foreign.stop()


def test_a_border_behind_a_same_origin_redirect_is_read(tmp_path: Path) -> None:
    border = Path(__file__).parents[3] / "acceptance/overland_route_planner_mvp/fixtures/road-map/poly/portugal.poly"
    service = redirecting(
        {
            "/p.poly": (307, {"Location": "/q.poly"}, b""),
            "/q.poly": (200, {}, border.read_bytes()),
        }
    )
    found = catalogue(service.url, tmp_path, FakeClock(), minimum=1)
    entry = CatalogueEntry("p", "P", None, f"{service.url}/p.osm.pbf", f"{service.url}/p.poly")
    assert found.outline_of(entry).rings
    service.stop()


def test_a_border_is_fetched_once_and_then_read_from_the_disk_even_after_a_restart(
    server: RecordingServer, tmp_path: Path
) -> None:
    clock = FakeClock()
    first = catalogue(server.url, tmp_path, clock)
    portugal = entry_of(first, "portugal")
    outline = first.outline_of(portugal)
    again = first.outline_of(portugal)
    restarted = catalogue(server.url, tmp_path, clock).outline_of(portugal)
    asked = server.requests("GET", ".poly")
    assert [a.path for a in asked] == ["/europe/portugal/portugal.poly"]
    assert asked[0].headers["user-agent"] == USER_AGENT
    assert outline == again == restarted and outline.rings


def test_a_border_that_does_not_come_or_does_not_read_is_unavailable_and_never_kept(
    server: RecordingServer, tmp_path: Path
) -> None:
    found = catalogue(server.url, tmp_path, FakeClock())
    missing = replace(entry_of(found, "portugal"), poly_url=f"{server.url}/nowhere.poly")
    with pytest.raises(CatalogueUnavailableError):
        found.outline_of(missing)
    elsewhere = replace(entry_of(found, "portugal"), poly_url="https://example.invalid/portugal.poly")
    with pytest.raises(CatalogueUnavailableError):  # off the list's own origin: nothing is asked
        found.outline_of(elsewhere)
    garbage = serving("this is not a polygon")
    broken = replace(entry_of(found, "portugal"), poly_url=f"{garbage.url}/portugal.poly")
    with pytest.raises(CatalogueUnavailableError):
        found.outline_of(broken)
    garbage.stop()
    assert list(tmp_path.rglob("*.poly")) == []
