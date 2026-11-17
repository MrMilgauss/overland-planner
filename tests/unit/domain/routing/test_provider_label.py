"""The header of a plan run's results names its road map, from the values the run stored (09-09, ADR-013 D250)."""

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from overland_planner.domain.routing.provider_label import provider_header

EPOCHS = st.integers(min_value=0, max_value=4_102_444_800)  # 1970 to 2100
VERSIONS = st.from_regex(r"[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}", fullmatch=True)
FACTORS = st.floats(min_value=1.0, max_value=5.0, allow_nan=False)
SCRIPTS = st.one_of(st.none(), st.from_regex(r"[0-9a-f]{64}", fullmatch=True))
UNKNOWN_IDS = st.one_of(
    st.text(alphabet=st.characters(blacklist_characters=":"), min_size=1, max_size=20),
    st.builds("valhalla:{}:{}".format, VERSIONS, st.from_regex(r"[a-z]{1,8}", fullmatch=True)),
    st.builds("mock:straight_line_x{}".format, st.from_regex(r"[a-z]{1,8}", fullmatch=True)),
)


@given(version=VERSIONS, epoch=EPOCHS)
def test_a_valhalla_run_names_the_utc_date_of_its_map_data_and_its_profile(version: str, epoch: int) -> None:
    date = datetime.fromtimestamp(epoch, UTC).date().isoformat()  # the oracle: the calendar, not the code's own text

    header = provider_header(f"valhalla:{version}:{epoch}", "4x4.v1")

    assert header == f"Provider: Valhalla (map data {date}) / profile: 4x4"


def test_a_valhalla_run_stored_with_the_recorded_status_names_its_map_data() -> None:
    # bypass: the worked example of ADR-013 Amendment 4 pins the date the property's oracle must agree with
    assert (
        provider_header("valhalla:3.9.1:1793560782", "4x4.v1")
        == "Provider: Valhalla (map data 2026-11-01) / profile: 4x4"
    )


@given(factor=FACTORS, script=SCRIPTS)
def test_an_offline_run_names_its_factor_whether_or_not_the_road_map_was_scripted(
    factor: float, script: str | None
) -> None:
    provider_id = f"mock:straight_line_x{factor}" + ("" if script is None else f":script:{script}")

    header = provider_header(provider_id, "mock.v1")

    assert header == f"Provider: offline estimate (straight line x {factor}) / profile: estimate"


@given(version=VERSIONS, epoch=EPOCHS, factor=FACTORS)
def test_a_run_stored_without_a_profile_shows_the_provider_part_only(version: str, epoch: int, factor: float) -> None:
    shown = {
        provider_header(f"valhalla:{version}:{epoch}", None),
        provider_header(f"mock:straight_line_x{factor}", None),
    }

    assert all(" / profile" not in header and header.startswith("Provider: ") for header in shown)


@given(provider_id=UNKNOWN_IDS, profile=st.one_of(st.none(), st.just("4x4.v1")))
def test_a_road_map_the_planner_does_not_know_is_shown_as_stored(provider_id: str, profile: str | None) -> None:
    header = provider_header(provider_id, profile)

    assert header.startswith(f"Provider: {provider_id}")


_MAX_EPOCH = 253_402_300_799  # 9999-12-31T23:59:59Z, the last second a date can show


@given(version=VERSIONS, epoch=st.one_of(st.integers(0, _MAX_EPOCH), st.sampled_from([0, _MAX_EPOCH])))
def test_an_epoch_a_date_can_show_names_its_utc_date_even_at_the_edges(version: str, epoch: int) -> None:
    date = datetime.fromtimestamp(epoch, UTC).date().isoformat()

    assert provider_header(f"valhalla:{version}:{epoch}", "4x4.v1") == (
        f"Provider: Valhalla (map data {date}) / profile: 4x4"
    )


@given(version=VERSIONS, epoch=st.one_of(st.integers(_MAX_EPOCH + 1, 10**18), st.just(_MAX_EPOCH + 1)))
def test_an_epoch_beyond_year_9999_shows_the_provider_id_as_stored(version: str, epoch: int) -> None:
    provider_id = f"valhalla:{version}:{epoch}"

    assert provider_header(provider_id, "4x4.v1") == f"Provider: {provider_id} / profile: 4x4"
