"""select_served: the served directory from the engine's answer and a listing; unknown is None, never an error.

Driving port: the pure function. Test Budget: 3 behaviors (match by epoch, match by name, unknown otherwise) x 2 = 6.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.roadmap.served_map import TilesetEntry, select_served

names = st.text("0123456789", min_size=8, max_size=8)
mtimes = st.integers(1_600_000_000, 1_900_000_000)


@st.composite
def listings(draw, unique_mtimes=True):
    dirs = draw(st.lists(names, min_size=1, max_size=6, unique=True))
    times = draw(st.lists(mtimes, min_size=len(dirs), max_size=len(dirs), unique=unique_mtimes))
    return tuple(TilesetEntry(n, t, True) for n, t in zip(dirs, times, strict=True))


@given(listing=listings(), data=st.data())
def test_epoch_equal_to_one_tar_mtime_selects_that_directory(listing, data):
    chosen = data.draw(st.sampled_from(listing))
    assert select_served(listing, chosen.tar_mtime) == chosen


@given(listing=listings(), data=st.data())
def test_directory_name_equal_to_the_id_selects_it(listing, data):
    chosen = data.draw(st.sampled_from(listing))
    assert select_served(listing, chosen.name) == chosen


@given(listing=listings(), epoch=mtimes, name=names)
def test_no_match_or_no_id_is_unknown(listing, epoch, name):
    assert select_served(listing, None) is None
    if all(e.tar_mtime != epoch for e in listing):
        assert select_served(listing, epoch) is None
    if all(e.name != name for e in listing):
        assert select_served(listing, name) is None
    assert select_served((), epoch) is None
    assert select_served((), name) is None


@given(listing=listings(), data=st.data())
def test_a_matching_directory_without_a_valid_record_is_unknown(listing, data):
    chosen = data.draw(st.sampled_from(listing))
    bare = tuple(TilesetEntry(e.name, e.tar_mtime, False) if e == chosen else e for e in listing)
    assert select_served(bare, chosen.tar_mtime) is None
    assert select_served(bare, chosen.name) is None


@given(listing=listings(), data=st.data())
def test_two_directories_with_the_same_mtime_select_none(listing, data):
    chosen = data.draw(st.sampled_from(listing))
    twin = TilesetEntry("twin-dir", chosen.tar_mtime, True)
    assert select_served((*listing, twin), chosen.tar_mtime) is None
