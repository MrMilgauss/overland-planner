"""The Nominatim adapter replayed with respx against a recorded real answer (q=Moab, fetched 2026-11-27): what is
sent (the typed words and nothing else), what is read, and how a bad answer is told. One live query is manual."""

from __future__ import annotations

import itertools
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.adapters.geocoding.nominatim_place_search import NominatimPlaceSearch, SwitchedOffPlaceSearch
from overland_planner.application.ports.place_search import PlaceHit, PlaceSearchUnavailableError

URL = "https://nominatim.example.test/search"
AGENT = "overland-planner/test (household trip planner; +https://github.com/MrMilgauss/overland-planner)"
RECORDED = (Path(__file__).parent / "fixtures" / "nominatim-moab-jsonv2.json").read_text(encoding="utf-8")


class FakeTime:
    """A monotonic clock whose sleep moves it: nothing in these tests really waits."""

    def __init__(self, start: float = 1000.0, *, sleeps: bool = True) -> None:
        self.now = start
        self._sleeps = sleeps

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        if self._sleeps:
            self.now += seconds


def adapter(url: str = URL, time: FakeTime | None = None) -> NominatimPlaceSearch:
    time = time or FakeTime()
    return NominatimPlaceSearch(url, user_agent=AGENT, monotonic=time.monotonic, sleep=time.sleep)


def sending(time: FakeTime, answer: httpx.Response | None = None) -> tuple[respx.Route, list[float]]:
    sent: list[float] = []

    def reply(request: httpx.Request) -> httpx.Response:
        sent.append(time.now)
        return answer or httpx.Response(200, json=[{"name": "Moab", "lat": "1", "lon": "2"}])

    return respx.get(URL).mock(side_effect=reply), sent


@given(
    gaps=st.lists(st.floats(min_value=0, max_value=5), min_size=2, max_size=8),
)
@settings(max_examples=40, deadline=None)
def test_different_searches_reach_the_service_at_least_a_second_apart(gaps: list[float]) -> None:
    time = FakeTime()
    with respx.mock:
        _, sent = sending(time)
        search = adapter(time=time)
        for number, gap in enumerate(gaps):
            time.now += gap
            search.search(f"place {number}")

    assert all(later - earlier >= 1.0 for earlier, later in itertools.pairwise(sent))


@given(count=st.integers(min_value=190, max_value=230))
@settings(max_examples=5, deadline=None)
def test_the_memory_holds_the_last_two_hundred_searches_only(count: int) -> None:
    time = FakeTime()
    kept = range(max(0, count - 200), count)
    with respx.mock:
        _, sent = sending(time)
        search = adapter(time=time)
        for number in range(count):
            search.search(f"place {number}")
        before = len(sent)
        for number in kept:
            search.search(f"place {number}")
        remembered = len(sent) == before
        if count > 200:
            search.search("place 0")

    assert remembered
    assert len(sent) - before == (1 if count > 200 else 0)


def test_the_same_search_within_a_day_is_answered_from_memory_and_after_a_day_is_sent_again() -> None:
    time = FakeTime()
    with respx.mock:
        _, sent = sending(time)
        search = adapter(time=time)
        first = search.search("Moab")
        time.now += 24 * 3600 - 1
        again = search.search("  moab ")
        time.now += 2
        search.search("Moab")

    assert again == first
    assert len(sent) == 2


def test_a_search_that_would_wait_more_than_three_seconds_is_busy_and_sends_nothing() -> None:
    time = FakeTime(sleeps=False)  # the clock stands still: every search queues behind the one before
    with respx.mock:
        _, sent = sending(time)
        search = adapter(time=time)
        for number in range(4):  # waits 0, 1, 2 and 3 s
            search.search(f"place {number}")
        with pytest.raises(PlaceSearchUnavailableError):
            search.search("one too many")

    assert len(sent) == 4


@pytest.mark.parametrize("status", [429, 503])
def test_after_a_busy_answer_nothing_is_sent_for_a_minute_then_the_next_search_goes_out(status: int) -> None:
    time = FakeTime()
    with respx.mock:
        route, sent = sending(time, httpx.Response(status, text="slow down"))
        search = adapter(time=time)
        with pytest.raises(PlaceSearchUnavailableError):
            search.search("Moab")
        time.now += 59
        with pytest.raises(PlaceSearchUnavailableError):
            search.search("Lagos")
        assert len(sent) == 1
        route.mock(return_value=httpx.Response(200, json=[]))
        time.now += 1.5
        assert search.search("Lagos") == ()


def test_two_identical_searches_at_once_send_one_request_and_both_get_the_answer() -> None:
    time = FakeTime()
    inside = threading.Event()
    release = threading.Event()
    with respx.mock:

        def slow(request: httpx.Request) -> httpx.Response:
            inside.set()
            release.wait(5)
            return httpx.Response(200, json=[{"name": "Moab", "lat": "1", "lon": "2"}])

        route = respx.get(URL).mock(side_effect=slow)
        search = adapter(time=time)
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(search.search, "Moab")
            inside.wait(5)
            second = pool.submit(search.search, "Moab")
            release.set()
            answers = (first.result(10), second.result(10))

    assert route.call_count == 1
    assert answers[0] == answers[1] != ()


def test_a_recorded_real_answer_reads_as_places_with_a_region_falling_back_when_the_state_is_missing() -> None:
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, text=RECORDED))
        hits = adapter().search("Moab")

    assert [(h.name, h.region, h.country) for h in hits] == [
        ("Moab", "Utah", "United States"),
        ("Newman Lake", "Washington", "United States"),
        ("Moab", "Davao Region", "Philippines"),
    ]
    assert hits[0] == PlaceHit("Moab", "Utah", "United States", 38.5738096, -109.546214, "Grand County")


STREET = (Path(__file__).parent / "fixtures" / "nominatim-street-address-jsonv2.json").read_text(encoding="utf-8")


def test_a_street_address_is_named_by_its_street_number_and_town_with_its_county_kept() -> None:
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, text=STREET))
        hits = adapter().search("Via Esempio 12")

    assert hits == (PlaceHit("Via Esempio 12, Paese Esempio", "Lombardia", "Italia", 45.464, 9.19, "Milano"),)


_WORDS = st.text(alphabet=st.characters(whitelist_categories=("L", "N", "Zs")), max_size=12)
_ADDRESS_KEYS = ("house_number", "road", "city", "town", "village", "hamlet", "suburb", "municipality", "county")


@given(
    address=st.dictionaries(st.sampled_from(_ADDRESS_KEYS), st.one_of(_WORDS, st.none(), st.integers()), max_size=9),
    name=st.one_of(st.just(""), st.none(), _WORDS),
    display=st.one_of(st.just(""), st.none(), st.lists(_WORDS, max_size=4).map(", ".join)),
)
@settings(max_examples=150, deadline=None)
def test_a_place_is_never_named_by_a_bare_number_or_nothing_whatever_the_address_lacks(
    address: dict[str, object], name: object, display: object
) -> None:
    row = {"lat": "1", "lon": "2", "name": name, "display_name": display, "address": address}
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, json=[row]))
        hits = adapter().search("anything")

    for hit in hits:
        assert hit.name.strip() != ""
        assert not hit.name.strip().isdigit()


@given(words=st.text(min_size=2, max_size=40).filter(lambda text: text.strip() != ""))
@settings(max_examples=40, deadline=None)
def test_only_the_typed_words_and_the_fixed_shape_are_sent(words: str) -> None:
    with respx.mock:
        route = respx.get(URL).mock(return_value=httpx.Response(200, text="[]"))
        adapter().search(words)
        request = route.calls.last.request

    query = parse_qs(urlsplit(str(request.url)).query, keep_blank_values=True)
    assert query == {"q": [words], "format": ["jsonv2"], "addressdetails": ["1"], "limit": ["5"]}
    assert request.headers["user-agent"] == AGENT
    assert set(request.headers) <= {"host", "user-agent", "accept", "accept-encoding", "connection"}


def test_at_most_five_places_are_kept() -> None:
    rows = [{"name": f"P{n}", "lat": "1", "lon": "2", "address": {"country": "X"}} for n in range(9)]
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, json=rows))
        hits = adapter().search("P")

    assert [h.name for h in hits] == [f"P{n}" for n in range(5)]


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(429, text="slow down"),
        httpx.Response(500, text="broken"),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"error": "no list"}),
        httpx.ConnectError("down"),
        httpx.ReadTimeout("slow"),
    ],
)
def test_a_service_that_is_busy_down_or_garbled_is_unavailable(answer: httpx.Response | Exception) -> None:
    with respx.mock:
        if isinstance(answer, Exception):
            respx.get(URL).mock(side_effect=answer)
        else:
            respx.get(URL).mock(return_value=answer)
        with pytest.raises(PlaceSearchUnavailableError):
            adapter().search("Moab")


def test_rows_without_a_point_or_a_name_are_left_out_and_a_missing_address_gives_empty_words() -> None:
    rows = [
        {"name": "No point", "address": {}},
        {"lat": "1", "lon": "2", "display_name": ""},
        {"lat": "3", "lon": "4", "display_name": "Lagos, Faro, Portugal"},
        "garbage",
    ]
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, text=json.dumps(rows)))
        hits = adapter().search("Lagos")

    assert hits == (PlaceHit("Lagos, Faro", "", "", 3.0, 4.0),)


@pytest.mark.parametrize(
    ("url", "outcome", "reason"),
    [
        (URL, "ok", None),
        ("http://127.0.0.1:8123/search", "ok", None),
        ("not an address", "degraded-healthy", "place_search_misconfigured"),
        ("ftp://host/search", "degraded-healthy", "place_search_misconfigured"),
        ("https:///search", "degraded-healthy", "place_search_misconfigured"),
    ],
)
def test_the_probe_checks_the_address_parses_and_sends_nothing(url: str, outcome: str, reason: str | None) -> None:
    with respx.mock:  # any outbound call would raise: no route is mocked
        result = adapter(url).probe()

    assert (result.outcome, result.reason) == (outcome, reason)


def test_switched_off_is_ok_with_its_words_and_never_searches() -> None:
    off = SwitchedOffPlaceSearch()

    assert (off.probe().outcome, off.probe().reason) == ("ok", "switched off")
    with pytest.raises(PlaceSearchUnavailableError):
        off.search("Moab")
