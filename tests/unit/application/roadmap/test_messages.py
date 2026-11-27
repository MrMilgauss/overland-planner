"""The words of a rebuild's result (D303, D304, D314): the planner's own sentences from a code and numbers."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.application.roadmap.messages import FAILURE_CODES, failure_message, success_message

MAP_DATE = datetime(2026, 11, 26, tzinfo=UTC)
NUMBERS = st.integers(min_value=0, max_value=100_000)
FORBIDDEN = re.compile(
    r"_|/|\.sh\b|script|docker|compose|refresh|\.txt|\bcode\b|deploy|valhalla|tileset", re.IGNORECASE
)


def failed(code: str | None, **kwargs: int | None) -> str:
    return failure_message(code, map_date=MAP_DATE, kept=True, **kwargs)


def test_every_failure_code_is_told_in_plain_words_with_the_previous_map_and_the_kept_change() -> None:
    assert len(FAILURE_CODES) == 14
    sentences = {code: failed(code, free_gb=18, need_gb=25, have_gb=9) for code in FAILURE_CODES}
    assert len(set(sentences.values())) == 14
    for sentence in sentences.values():
        assert not FORBIDDEN.search(sentence), sentence
        assert sentence.startswith("The rebuild didn't finish")
        assert "The previous road map is back (map data 26 November 2026)" in sentence
        assert "Your change is kept" in sentence and "press Rebuild road map again" in sentence


@given(free=NUMBERS, need=NUMBERS)
def test_the_disk_sentence_carries_the_free_and_the_needed_gigabytes(free: int, need: int) -> None:
    assert f"the Pi has {free} GB of free disk and needs {need} GB" in failed("disk", free_gb=free, need_gb=need)


@given(have=NUMBERS)
def test_the_memory_sentence_carries_the_gigabytes_the_pi_has(have: int) -> None:
    assert f"{have} GB of memory" in failed("memory", have_gb=have)


def test_the_disk_sentence_without_numbers_still_says_the_disk_is_short() -> None:
    sentence = failed("disk")
    assert "disk" in sentence and "GB" not in sentence


def test_a_rebuild_that_ran_out_of_memory_says_so() -> None:
    assert "the Pi ran out of memory building the map" in failed("build_oom")


@given(code=st.one_of(st.none(), st.from_regex(r"[a-z]{3,12}_[a-z]{3,12}", fullmatch=True)))
def test_an_unknown_code_reads_as_a_generic_failure_that_never_shows_the_code(code: str | None) -> None:
    sentence = failed(code)
    assert sentence.startswith("The rebuild didn't finish") and "previous road map is back" in sentence
    assert code is None or code not in sentence


def test_without_a_change_to_keep_or_a_date_the_sentence_says_neither() -> None:
    sentence = failure_message("download", map_date=None, kept=False)
    assert "Your change is kept" not in sentence and "map data" not in sentence
    assert "The previous road map is back" in sentence


@pytest.mark.parametrize(
    ("added", "removed", "expected"),
    [
        (["Utah"], [], "Road map rebuilt on 27 November at 02:56. Utah added; 9 regions, map data 27 November 2026."),
        (
            ["Utah", "Peru"],
            ["Spain"],
            "Road map rebuilt on 27 November at 02:56. Utah and Peru added, Spain removed; "
            "9 regions, map data 27 November 2026.",
        ),
        ([], [], "Road map rebuilt on 27 November at 02:56. 9 regions, map data 27 November 2026."),
    ],
)
def test_a_rebuild_that_ended_well_names_what_changed_the_count_and_the_dates(
    added: list[str], removed: list[str], expected: str
) -> None:
    done = datetime(2026, 11, 27, 2, 56, tzinfo=UTC)
    sentence = success_message(finished_at=done, added=added, removed=removed, region_count=9, map_date=done)
    assert sentence == expected
