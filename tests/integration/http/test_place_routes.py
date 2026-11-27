"""`GET /api/places/search?q=` through the route and the facade with a recording port (D307, ADR-019): the two-letter
rule and the answer's shape. The adapter's wire facts are in tests/unit/adapters/geocoding."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from overland_planner.adapters.http.errors import install_error_handlers
from overland_planner.adapters.http.place_routes import place_routes
from overland_planner.application.ports.place_search import PlaceHit, PlaceSearchUnavailableError
from overland_planner.application.ports.probe import ProbeResult
from overland_planner.application.roadmap.facade import PlaceSearchService


class _NoLog:
    def info(self, event: str, **fields: object) -> None: ...

    def warning(self, event: str, **fields: object) -> None: ...

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


class RecordingPlaces:
    def __init__(self, *, down: bool = False) -> None:
        self.asked: list[str] = []
        self._down = down

    def search(self, words: str) -> tuple[PlaceHit, ...]:
        self.asked.append(words)
        if self._down:
            raise PlaceSearchUnavailableError
        return (PlaceHit("Lagos", "Algarve", "Portugal", 37.1, -8.67),)

    def probe(self) -> ProbeResult:
        return ProbeResult(outcome="ok")


def client(places: RecordingPlaces) -> TestClient:
    app = FastAPI()
    install_error_handlers(app, _NoLog())
    app.include_router(place_routes(PlaceSearchService(places)))
    return TestClient(app)


@given(words=st.text(max_size=12).filter(lambda text: len(" ".join(text.split())) < 2))
@settings(max_examples=40, deadline=None)
def test_a_name_under_two_letters_is_refused_and_nothing_is_asked(words: str) -> None:
    places = RecordingPlaces()

    answer = client(places).get("/api/places/search", params={"q": words})

    assert (answer.status_code, places.asked) == (422, [])


@given(words=st.from_regex(r"[A-Za-z]{2,10}( [A-Za-z]{2,10}){0,2}", fullmatch=True))
@settings(max_examples=40, deadline=None)
def test_a_name_is_asked_once_as_typed_and_answered_with_its_places(words: str) -> None:
    places = RecordingPlaces()

    answer = client(places).get("/api/places/search", params={"q": f"  {words}  "})

    assert answer.status_code == 200
    assert answer.json() == [{"name": "Lagos", "region": "Algarve", "country": "Portugal", "lat": 37.1, "lon": -8.67}]
    assert places.asked == [words]


def test_a_service_that_cannot_answer_is_a_503_with_its_code() -> None:
    answer = client(RecordingPlaces(down=True)).get("/api/places/search", params={"q": "Lagos"})

    assert (answer.status_code, answer.json()["code"]) == (503, "place_search_unavailable")
