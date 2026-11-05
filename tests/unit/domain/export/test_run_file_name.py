"""An exported plan run gets a safe, predictable file name (US-02b, slice 01b).

Driving port: the pure function `run_file_name`. Observable universe: the `file_name` it answers.
Test Budget: 3 behaviors (the name reads project then run; accents and case fold away and everything else becomes one
hyphen; a name with nothing usable, or too long for a file system, still gives a file name) x 2 = 6; 5 used.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.export.run_file_name import run_file_name
from tests.common.state_delta import assert_state_delta, set_to

UNIVERSE = {"file_name"}
LONGEST_FILE_NAME = 255  # the common limit of file systems, in bytes
BEFORE: dict[str, str | None] = {"file_name": None}
ACCENT = "́"

_run_numbers = st.integers(1, 100_000)
_words = st.text(alphabet="abcdefgxyz", min_size=1, max_size=12)
_nothing_usable = st.text(alphabet=" -_.,;:!?'\"\\/\r\n\t()&%$€·—", max_size=30)


def _assert_file_name(project_name: str, run_number: int, expected: Any) -> None:
    after = {"file_name": run_file_name(project_name, run_number)}
    assert_state_delta(BEFORE, after, UNIVERSE, {"file_name": expected}, strict=True)


def _safe_for(run_number: int) -> Any:
    shape = re.compile(rf"[a-z0-9]+(-[a-z0-9]+)*-run{run_number}\.gpx")

    def _is_safe(_old: Any, new: str) -> bool:
        return shape.fullmatch(new) is not None and len(new) <= LONGEST_FILE_NAME

    return _is_safe


# bypass: the exact names the slice's feature text and the rule's edge cases fix; generated text cannot state them.
@pytest.mark.parametrize(
    ("project_name", "run_number", "file_name"),
    [
        ("Alpi Occidentali giugno 2027", 1, "alpi-occidentali-giugno-2027-run1.gpx"),
        ("Côte d'Azur & Provence!", 12, "cote-d-azur-provence-run12.gpx"),
        ('evil"\r\nX-Injected: yes', 3, "evil-x-injected-yes-run3.gpx"),
        ("---", 2, "plan-run2.gpx"),
        ("東京", 4, "plan-run4.gpx"),
    ],
)
def test_the_file_name_reads_the_project_then_the_run(project_name: str, run_number: int, file_name: str) -> None:
    _assert_file_name(project_name, run_number, set_to(file_name))


@given(project_name=st.text(max_size=60), run_number=_run_numbers)
def test_any_project_name_gives_a_safe_ascii_file_name(project_name: str, run_number: int) -> None:
    _assert_file_name(project_name, run_number, _safe_for(run_number))


@given(words=st.lists(_words, min_size=1, max_size=5), run_number=_run_numbers)
def test_accents_and_case_do_not_change_the_file_name(words: list[str], run_number: int) -> None:
    plain = " ".join(words)
    accented = unicodedata.normalize("NFC", "".join(f"{letter}{ACCENT}" for letter in plain)).upper()

    _assert_file_name(accented, run_number, set_to(f"{'-'.join(words)}-run{run_number}.gpx"))


@given(project_name=_nothing_usable, run_number=_run_numbers)
def test_a_name_with_nothing_usable_falls_back_to_plan(project_name: str, run_number: int) -> None:
    _assert_file_name(project_name, run_number, set_to(f"plan-run{run_number}.gpx"))


@given(word=_words, repeats=st.integers(100, 400), run_number=_run_numbers)
def test_a_very_long_project_name_still_fits_a_file_system(word: str, repeats: int, run_number: int) -> None:
    _assert_file_name(f"{word} " * repeats, run_number, _safe_for(run_number))
