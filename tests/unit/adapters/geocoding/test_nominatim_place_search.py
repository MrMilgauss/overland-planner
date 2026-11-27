"""The Nominatim adapter replayed with respx against a recorded real answer (q=Moab, fetched 2026-11-27): what is
sent (the typed words and nothing else), what is read, and how a bad answer is told. One live query is manual."""

from __future__ import annotations

import json
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


def adapter(url: str = URL) -> NominatimPlaceSearch:
    return NominatimPlaceSearch(url, user_agent=AGENT)


def test_a_recorded_real_answer_reads_as_places_with_a_region_falling_back_when_the_state_is_missing() -> None:
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, text=RECORDED))
        hits = adapter().search("Moab")

    assert [(h.name, h.region, h.country) for h in hits] == [
        ("Moab", "Utah", "United States"),
        ("Newman Lake", "Washington", "United States"),
        ("Moab", "Davao Region", "Philippines"),
    ]
    assert hits[0] == PlaceHit("Moab", "Utah", "United States", 38.5738096, -109.546214)


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

    assert hits == (PlaceHit("Lagos", "", "", 3.0, 4.0),)


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
