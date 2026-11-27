"""Settings parsing properties (driving port: `Settings.from_environ`, the composition root's config gate).

Universe = the settings the planner reads (brief section 12 keys + WEB_DIST_DIR + MIGRATIONS_DIR), named by their
environment key. The shared household password (PLANNER_BASIC_AUTH_USER / _PASSWORD) is set as a pair or not at all.
The upload caps (MAX_UPLOAD_*) are positive integers; zero or negative refuses the start (ADR-011 Amendment 1).
The solve limits (FEASIBILITY_LIMIT_S, OPTIMISATION_LIMIT_S; ADR-014 section 2, D116) are whole seconds above 0 and the
feasibility limit may not exceed the optimisation limit; their own property draws the pair, so the generic environments
leave them unset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.bootstrap.settings import InvalidSettingsError, Settings
from tests.common.state_delta import assert_state_delta, set_to, unchanged

KEYS = (
    "DATA_DIR",
    "LOG_LEVEL",
    "ROUTING_PROVIDER",
    "SOLVER_BUDGET",
    "PLANNER_GIT_SHA",
    "WEB_DIST_DIR",
    "MIGRATIONS_DIR",
    "PLANNER_BASIC_AUTH_USER",
    "PLANNER_BASIC_AUTH_PASSWORD",
    "MAX_UPLOAD_FILE_MB",
    "MAX_UPLOAD_REQUEST_MB",
    "MAX_UPLOAD_FILES",
    "FEASIBILITY_LIMIT_S",
    "OPTIMISATION_LIMIT_S",
    "VALHALLA_URL",
    "VALHALLA_EXPECTED_VERSION",
    "VALHALLA_MAX_MATRIX_PAIRS",
    "VALHALLA_CONCURRENCY",
    "CONFIRMED_SNAP_M",
)
ENGINE_DEFAULTS = {
    "VALHALLA_URL": "http://valhalla:8002",
    "VALHALLA_EXPECTED_VERSION": "3.9.1",
    "VALHALLA_MAX_MATRIX_PAIRS": 2500,
    "VALHALLA_CONCURRENCY": 2,
    "CONFIRMED_SNAP_M": 250,
}  # ADR-013 Amendment 4, D247
LIMITS = ("FEASIBILITY_LIMIT_S", "OPTIMISATION_LIMIT_S")
LIMIT_DEFAULTS = {"FEASIBILITY_LIMIT_S": 600, "OPTIMISATION_LIMIT_S": 1800}  # ADR-014 section 2
UPLOAD_CAPS = ("MAX_UPLOAD_FILE_MB", "MAX_UPLOAD_REQUEST_MB", "MAX_UPLOAD_FILES")
AUTH_PAIR = ("PLANNER_BASIC_AUTH_USER", "PLANNER_BASIC_AUTH_PASSWORD")
UNIVERSE = set(KEYS)

_segment = st.from_regex(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,11}", fullmatch=True)
_path = st.lists(_segment, min_size=1, max_size=4).map(lambda parts: "/" + "/".join(parts))
_printable = st.text(st.characters(min_codepoint=33, max_codepoint=126), min_size=1, max_size=40)
_secret_char = st.characters(exclude_categories=("Cs",), exclude_characters="\x00")

# Raw environment text -> the value the planner must see for it.
VALID: dict[str, st.SearchStrategy[tuple[str, Any]]] = {
    "DATA_DIR": _path.map(lambda raw: (raw, Path(raw))),
    "LOG_LEVEL": st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR"]).map(lambda raw: (raw, raw)),
    "ROUTING_PROVIDER": st.sampled_from(["mock", "valhalla"]).map(lambda raw: (raw, raw)),
    "SOLVER_BUDGET": st.integers(min_value=1, max_value=10**7).map(lambda n: (str(n), n)),
    "PLANNER_GIT_SHA": _printable.map(lambda raw: (raw, raw)),
    "WEB_DIST_DIR": _path.map(lambda raw: (raw, Path(raw))),
    "MIGRATIONS_DIR": _path.map(lambda raw: (raw, Path(raw))),
    "PLANNER_BASIC_AUTH_USER": st.text(_secret_char.filter(lambda c: c != ":"), min_size=1).map(lambda raw: (raw, raw)),
    "PLANNER_BASIC_AUTH_PASSWORD": st.text(_secret_char, min_size=1).map(lambda raw: (raw, raw)),
    **{cap: st.integers(min_value=1, max_value=10**4).map(lambda n: (str(n), n)) for cap in UPLOAD_CAPS},
    "VALHALLA_URL": st.tuples(st.sampled_from(["http", "https"]), _segment, st.integers(1, 65535)).map(
        lambda p: (f"{p[0]}://{p[1]}:{p[2]}", f"{p[0]}://{p[1]}:{p[2]}")
    ),
    "VALHALLA_EXPECTED_VERSION": _printable.map(lambda raw: (raw, raw)),
    "VALHALLA_MAX_MATRIX_PAIRS": st.integers(min_value=1, max_value=10**6).map(lambda n: (str(n), n)),
    "VALHALLA_CONCURRENCY": st.integers(min_value=1, max_value=8).map(lambda n: (str(n), n)),
    "CONFIRMED_SNAP_M": st.integers(min_value=1, max_value=10**5).map(lambda n: (str(n), n)),
}

INVALID: dict[str, st.SearchStrategy[str]] = {
    "DATA_DIR": st.just(""),
    "LOG_LEVEL": _printable.filter(lambda raw: raw not in {"DEBUG", "INFO", "WARNING", "ERROR"}),
    "ROUTING_PROVIDER": _printable.filter(lambda raw: raw not in {"mock", "valhalla"}),
    "SOLVER_BUDGET": st.integers(max_value=0).map(str) | st.from_regex(r"[A-Za-z]{1,8}", fullmatch=True),
    "PLANNER_GIT_SHA": st.just(""),
    "WEB_DIST_DIR": st.just(""),
    "MIGRATIONS_DIR": st.just(""),
    # RFC 7617: the user part of Basic credentials ends at the first colon, so such a user could never log in.
    "PLANNER_BASIC_AUTH_USER": st.tuples(st.text(max_size=5), st.text(max_size=5)).map(lambda p: f"{p[0]}:{p[1]}"),
    **{cap: st.integers(max_value=0).map(str) | st.from_regex(r"[A-Za-z]{1,8}", fullmatch=True) for cap in UPLOAD_CAPS},
    # http or https with a host: another scheme, no scheme, or no host is refused
    "VALHALLA_URL": st.sampled_from(["ftp://valhalla:8002", "valhalla:8002", "http://", "https:///path", "//valhalla"]),
    "VALHALLA_MAX_MATRIX_PAIRS": st.integers(max_value=0).map(str) | st.from_regex(r"[A-Za-z]{1,8}", fullmatch=True),
    "VALHALLA_CONCURRENCY": st.integers(max_value=0).map(str)
    | st.integers(min_value=9).map(str)
    | st.from_regex(r"[A-Za-z]{1,8}", fullmatch=True),
    "CONFIRMED_SNAP_M": st.integers(max_value=0).map(str) | st.from_regex(r"[A-Za-z]{1,8}", fullmatch=True),
}

# Keys the planner does not read: other variables, and lower-case spellings of its own keys (keys are case-sensitive).
_unrelated_key = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,15}", fullmatch=True).filter(lambda key: key not in UNIVERSE)


def observable(settings: Settings) -> dict[str, Any]:
    return {
        "DATA_DIR": settings.data_dir,
        "LOG_LEVEL": settings.log_level,
        "ROUTING_PROVIDER": settings.routing_provider,
        "SOLVER_BUDGET": settings.solver_budget,
        "PLANNER_GIT_SHA": settings.planner_git_sha,
        "WEB_DIST_DIR": settings.web_dist_dir,
        "MIGRATIONS_DIR": settings.migrations_dir,
        "PLANNER_BASIC_AUTH_USER": settings.basic_auth_user,
        "PLANNER_BASIC_AUTH_PASSWORD": (
            settings.basic_auth_password.get_secret_value() if settings.basic_auth_password else None
        ),
        "MAX_UPLOAD_FILE_MB": settings.max_upload_file_mb,
        "MAX_UPLOAD_REQUEST_MB": settings.max_upload_request_mb,
        "MAX_UPLOAD_FILES": settings.max_upload_files,
        "FEASIBILITY_LIMIT_S": settings.feasibility_limit_s,
        "OPTIMISATION_LIMIT_S": settings.optimisation_limit_s,
        "VALHALLA_URL": settings.valhalla_url,
        "VALHALLA_EXPECTED_VERSION": settings.valhalla_expected_version,
        "VALHALLA_MAX_MATRIX_PAIRS": settings.valhalla_max_matrix_pairs,
        "VALHALLA_CONCURRENCY": settings.valhalla_concurrency,
        "CONFIRMED_SNAP_M": settings.confirmed_snap_m,
    }


@st.composite
def environments(draw: st.DrawFn) -> tuple[dict[str, str], dict[str, Any]]:
    """A process environment with any subset of the planner's keys set to valid values, plus unrelated keys."""
    chosen = draw(st.lists(st.sampled_from([key for key in KEYS if key not in LIMITS]), unique=True))
    if set(chosen) & set(AUTH_PAIR):
        chosen = list(dict.fromkeys([*chosen, *AUTH_PAIR]))
    environ: dict[str, str] = draw(st.dictionaries(_unrelated_key, _printable, max_size=5))
    environ.update(draw(st.dictionaries(st.sampled_from([k.lower() for k in KEYS]), _printable, max_size=3)))
    expected: dict[str, Any] = {}
    for key in chosen:
        raw, value = draw(VALID[key])
        environ[key] = raw
        expected[key] = value
    return environ, expected


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@given(case=environments())
def test_valid_settings_parse_to_their_values_and_unrelated_keys_are_ignored(
    case: tuple[dict[str, str], dict[str, Any]],
) -> None:
    environ, expected_values = case
    before = observable(Settings.from_environ({}))
    after = observable(Settings.from_environ(environ))
    assert_state_delta(
        before,
        after,
        universe=UNIVERSE,
        expected={key: set_to(expected_values[key]) if key in expected_values else unchanged() for key in KEYS},
        strict=True,
    )


@given(data=st.data(), key=st.sampled_from(sorted(INVALID)))
def test_a_value_outside_its_domain_is_refused_naming_its_key(data: st.DataObject, key: str) -> None:
    # bypass: a refusal leaves no settings to diff; the error's named keys are its whole observable surface.
    environ = {key: data.draw(INVALID[key], label=key)}
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ(environ)
    assert refused.value.setting_names == frozenset({key})
    assert key in str(refused.value)


@given(provider=_printable.filter(lambda raw: raw not in {"mock", "valhalla"}))
def test_invalid_routing_provider_is_refused(provider: str) -> None:
    # bypass: refusal path, see above. Only `mock` and `valhalla` are accepted.
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"ROUTING_PROVIDER": provider, "PLANNER_GIT_SHA": "abc123def456"})
    assert refused.value.setting_names == frozenset({"ROUTING_PROVIDER"})
    assert "ROUTING_PROVIDER" in str(refused.value)


@given(
    present=st.sampled_from(AUTH_PAIR),
    value=st.text(_secret_char.filter(lambda c: c != ":"), min_size=1),
    other_empty=st.booleans(),
)
def test_the_shared_password_set_without_its_user_or_the_reverse_is_refused(
    present: str, value: str, other_empty: bool
) -> None:
    # bypass: refusal path, see above. An empty value counts as unset (a `KEY=` line in the settings file).
    (missing,) = set(AUTH_PAIR) - {present}
    environ = {present: value, **({missing: ""} if other_empty else {})}
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ(environ)
    assert refused.value.setting_names == frozenset({missing})
    assert missing in str(refused.value)


@pytest.mark.heavy_property  # >= 3 s at profile ci (D221 pattern, 2026-11-10): slow-properties job
@given(case=environments(), empty_caps=st.lists(st.sampled_from(UPLOAD_CAPS), unique=True, min_size=1))
def test_an_empty_upload_cap_falls_back_to_its_default(
    case: tuple[dict[str, str], dict[str, Any]], empty_caps: list[str]
) -> None:
    # compose.yaml passes every cap as `${MAX_UPLOAD_...:-}`: a cap missing from .env reaches the planner as `KEY=`.
    environ, expected_values = case
    environ.update(dict.fromkeys(empty_caps, ""))
    before = observable(Settings.from_environ({}))
    after = observable(Settings.from_environ(environ))
    assert_state_delta(
        before,
        after,
        universe=UNIVERSE,
        expected={
            key: set_to(expected_values[key]) if key in expected_values and key not in empty_caps else unchanged()
            for key in KEYS
        },
        strict=True,
    )


# Texts that are not a whole number of seconds above 0 (D116): zero, negatives, decimals, exponents, padding, words,
# empty, and digits outside ASCII.
_not_whole_seconds = st.one_of(
    st.integers(max_value=0).map(str),
    st.integers(min_value=0, max_value=10**4).map(lambda n: f"{n}.0"),
    st.integers(min_value=1, max_value=10**4).map(lambda n: f"{n}.5"),
    st.sampled_from(["", " 30", "30 ", "1e3", "+30", "30s", "thirty", "\u0663\u0660", "0x1e"]),
)


@st.composite
def limit_settings(draw: st.DrawFn) -> tuple[dict[str, str], dict[str, int | None]]:
    """Each limit absent, a whole number of seconds above 0 (leading zeros allowed) or anything else; the expected
    value is the drawn number, the default when absent, `None` when the text is not whole seconds above 0."""
    environ: dict[str, str] = {}
    meant: dict[str, int | None] = {}
    for key in LIMITS:
        kind = draw(st.sampled_from(["absent", "whole", "not_whole"]), label=key)
        if kind == "absent":
            meant[key] = LIMIT_DEFAULTS[key]
        elif kind == "whole":
            seconds = draw(st.integers(min_value=1, max_value=10**5))
            environ[key] = "0" * draw(st.integers(0, 2)) + str(seconds)
            meant[key] = seconds
        else:
            environ[key] = draw(_not_whole_seconds)
            meant[key] = None
    return environ, meant


@given(case=limit_settings())
def test_the_start_up_accepts_the_limits_iff_both_are_whole_seconds_and_feasibility_fits_in_optimisation(
    case: tuple[dict[str, str], dict[str, int | None]],
) -> None:
    environ, meant = case
    not_whole = frozenset(key for key in LIMITS if meant[key] is None)
    feasibility, optimisation = meant["FEASIBILITY_LIMIT_S"], meant["OPTIMISATION_LIMIT_S"]
    too_long = not not_whole and feasibility is not None and optimisation is not None and feasibility > optimisation
    refused = not_whole or (frozenset({"FEASIBILITY_LIMIT_S"}) if too_long else frozenset())

    before = {**observable(Settings.from_environ({})), "refused": frozenset()}
    try:
        after = {**observable(Settings.from_environ(environ)), "refused": frozenset()}
    except InvalidSettingsError as error:
        assert all(key in str(error) for key in error.setting_names), "the refusal names each key it refuses"
        after = {**dict.fromkeys(KEYS), "refused": error.setting_names}

    if refused:
        expected = {**{key: set_to(None) for key in KEYS}, "refused": set_to(refused)}
    else:
        expected = {key: set_to(meant[key]) if key in environ else unchanged() for key in KEYS}
    assert_state_delta(before, after, universe=UNIVERSE | {"refused"}, expected=expected, strict=True)


@given(key=st.sampled_from(sorted(ENGINE_DEFAULTS)))
def test_an_empty_engine_setting_is_its_default(key: str) -> None:
    # compose passes `${KEY:-}`: an unset key arrives as an empty value and must read as the default (D247).
    before = observable(Settings.from_environ({}))
    after = observable(Settings.from_environ({key: ""}))
    assert_state_delta(before, after, universe=UNIVERSE, expected={k: unchanged() for k in KEYS}, strict=True)
    assert after[key] == ENGINE_DEFAULTS[key]


def test_the_engine_defaults_are_the_documented_ones() -> None:
    # bypass: the defaults are the contract of D247; a single example is the rule.
    settings = Settings.from_environ({})
    assert settings.routing_provider == "mock"
    assert {key: observable(settings)[key] for key in ENGINE_DEFAULTS} == ENGINE_DEFAULTS


@given(plan=_path)
def test_the_offline_road_map_script_with_the_valhalla_provider_is_refused(plan: str) -> None:
    # bypass: refusal path; the error's named keys are its whole observable surface.
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"ROUTING_PROVIDER": "valhalla", "MOCK_PLAN": plan})
    assert refused.value.setting_names == frozenset({"MOCK_PLAN"})
    assert Settings.from_environ({"ROUTING_PROVIDER": "mock", "MOCK_PLAN": plan}).mock_plan == Path(plan)


# --------------------------------------------------------------------------- map tiles (ADR-004, step 10-03)
TILE_DEFAULTS = {
    "MAP_TILE_URL": "https://tile.opentopomap.org/{z}/{x}/{y}.png",
    "MAP_TILE_ATTRIBUTION": "Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)",
    "MAP_TILE_MAX_ZOOM": 17,
}
TILE_UNIVERSE = frozenset(TILE_DEFAULTS)
_host = st.from_regex(r"[a-z]{1,8}(\.[a-z]{1,8}){0,2}", fullmatch=True)
_tile_path = st.sampled_from(["/{z}/{x}/{y}.png", "/t/{z}/{x}/{y}.jpg", "/{z}/{y}/{x}"])
_secret_value = st.from_regex(r"[0-9a-f]{16,32}", fullmatch=True)  # never a substring of any fixed message text
_key_words = st.sampled_from(
    [
        *("key", "token", "secret", "signature", "auth", "sig", "apikey", "api_key"),
        *("appid", "app_id", "password", "pwd", "access", "client_id"),
    ]
)
_case = st.sampled_from([str.lower, str.upper, str.title])


def tile_view(settings: Settings) -> dict[str, Any]:
    return {
        "MAP_TILE_URL": settings.map_tile_url,
        "MAP_TILE_ATTRIBUTION": settings.map_tile_attribution,
        "MAP_TILE_MAX_ZOOM": settings.map_tile_max_zoom,
    }


@given(key=st.sampled_from(sorted(TILE_DEFAULTS)))
def test_an_empty_or_absent_map_tile_setting_is_its_default(key: str) -> None:
    # compose passes `${KEY:-}`: an unset key arrives empty and must read as the default (ADR-004).
    before = tile_view(Settings.from_environ({}))
    after = tile_view(Settings.from_environ({key: ""}))
    assert before == TILE_DEFAULTS
    assert_state_delta(before, after, universe=TILE_UNIVERSE, expected={k: unchanged() for k in TILE_UNIVERSE})


@given(
    scheme=st.sampled_from(["http", "https"]),
    host=_host,
    path=_tile_path,
    param=st.sampled_from(["", "?style=a", "?v=2&lang=it"]),
    attribution=st.text(min_size=1, max_size=40).filter(lambda text: text.strip() == text and text != ""),
    zoom=st.integers(1, 22),
)
def test_a_usable_tile_address_attribution_and_zoom_are_taken_as_given(
    scheme: str, host: str, path: str, param: str, attribution: str, zoom: int
) -> None:
    url = f"{scheme}://{host}{path}{param}"
    before = tile_view(Settings.from_environ({}))
    after = tile_view(
        Settings.from_environ(
            {"MAP_TILE_URL": url, "MAP_TILE_ATTRIBUTION": attribution, "MAP_TILE_MAX_ZOOM": str(zoom)}
        )
    )
    expected = {
        "MAP_TILE_URL": set_to(url),
        "MAP_TILE_ATTRIBUTION": set_to(attribution),
        "MAP_TILE_MAX_ZOOM": set_to(zoom),
    }
    assert_state_delta(before, after, universe=TILE_UNIVERSE, expected=expected, strict=True)


@given(
    url=st.sampled_from(
        [
            "ftp://tiles.test/{z}/{x}/{y}.png",
            "tiles.test/{z}/{x}/{y}.png",
            "https:///{z}/{x}/{y}.png",
            "https://tiles.test/{x}/{y}.png",
            "https://tiles.test/{z}/{y}.png",
            "https://tiles.test/{z}/{x}.png",
            "https://tiles.test/tiles.png",
        ]
    )
)
def test_a_tile_address_that_is_not_http_with_a_host_and_all_three_placeholders_is_refused(url: str) -> None:
    # bypass: refusal path; a refusal leaves no settings to diff, the named keys are its whole observable surface.
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"MAP_TILE_URL": url})
    assert refused.value.setting_names == frozenset({"MAP_TILE_URL"})


@given(
    host=_host,
    secret=_secret_value,
    part=st.sampled_from(["userinfo", "fragment"]),
)
def test_a_tile_address_with_userinfo_or_a_fragment_is_refused_naming_the_part_but_never_its_value(
    host: str, secret: str, part: str
) -> None:
    userinfo = f"user:{secret}@" if part == "userinfo" else ""
    fragment = f"#{secret}" if part == "fragment" else ""
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"MAP_TILE_URL": f"https://{userinfo}{host}/{{z}}/{{x}}/{{y}}.png{fragment}"})
    message = str(refused.value)
    assert refused.value.setting_names == frozenset({"MAP_TILE_URL"})
    assert "MAP_TILE_URL" in message and part in message
    assert secret not in message
    assert secret not in repr(refused.value) and secret not in repr(refused.value.__cause__)


@given(zoom=st.sampled_from(["0", "-1", "23", "100", "high", "1.5"]))
def test_a_maximum_zoom_outside_1_to_22_is_refused(zoom: str) -> None:
    # bypass: refusal path, see above.
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"MAP_TILE_MAX_ZOOM": zoom})
    assert refused.value.setting_names == frozenset({"MAP_TILE_MAX_ZOOM"})


@given(
    host=_host,
    word=_key_words,
    case=_case,
    before_word=st.from_regex(r"[a-z_]{0,6}", fullmatch=True),
    after_word=st.from_regex(r"[a-z_]{0,6}", fullmatch=True),
    value=_secret_value,
    other=st.sampled_from(["", "style=a&", "v=2&"]),
)
def test_a_tile_address_carrying_a_private_parameter_is_refused_naming_the_parameter_but_never_its_value(
    host: str, word: str, case: Any, before_word: str, after_word: str, value: str, other: str
) -> None:
    name = case(f"{before_word}{word}{after_word}")
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"MAP_TILE_URL": f"https://{host}/{{z}}/{{x}}/{{y}}.png?{other}{name}={value}"})
    message = str(refused.value)
    assert refused.value.setting_names == frozenset({"MAP_TILE_URL"})
    assert "MAP_TILE_URL" in message and f"carries the private parameter {name}" in message
    assert value not in message
    assert value not in repr(refused.value) and value not in repr(refused.value.__cause__)


# --------------------------------------------------------------------------- light base map (ADR-004 Am. 1, D287)
BASE_DEFAULTS = {
    "MAP_BASE_STYLE_URL": "https://tiles.openfreemap.org/styles/positron",
    "MAP_BASE_ATTRIBUTION": "© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors",
}
BASE_UNIVERSE = frozenset(BASE_DEFAULTS)
_style_path = st.sampled_from(["/styles/positron", "/s/light.json", "/style"])


def base_view(settings: Settings) -> dict[str, Any]:
    return {
        "MAP_BASE_STYLE_URL": settings.map_base_style_url,
        "MAP_BASE_ATTRIBUTION": settings.map_base_attribution,
    }


@given(key=st.sampled_from(sorted(BASE_DEFAULTS)), blank=st.sampled_from(["", "   ", " \t"]))
def test_an_empty_or_blank_light_base_map_setting_is_its_default(key: str, blank: str) -> None:
    before = base_view(Settings.from_environ({}))
    after = base_view(Settings.from_environ({key: blank}))
    assert before == BASE_DEFAULTS
    assert_state_delta(before, after, universe=BASE_UNIVERSE, expected={k: unchanged() for k in BASE_UNIVERSE})


@given(
    scheme=st.sampled_from(["http", "https"]),
    host=_host,
    path=_style_path,
    param=st.sampled_from(["", "?lang=it", "?v=2&lang=it"]),
    attribution=st.text(min_size=1, max_size=40).filter(lambda text: text.strip() == text and text != ""),
)
def test_a_clean_light_base_map_address_and_credit_are_taken_as_given(
    scheme: str, host: str, path: str, param: str, attribution: str
) -> None:
    url = f"{scheme}://{host}{path}{param}"
    before = base_view(Settings.from_environ({}))
    after = base_view(Settings.from_environ({"MAP_BASE_STYLE_URL": url, "MAP_BASE_ATTRIBUTION": attribution}))
    expected = {"MAP_BASE_STYLE_URL": set_to(url), "MAP_BASE_ATTRIBUTION": set_to(attribution)}
    assert_state_delta(before, after, universe=BASE_UNIVERSE, expected=expected, strict=True)


@given(url=st.sampled_from(["ftp://styles.test/s.json", "styles.test/s.json", "https:///s.json"]))
def test_a_light_base_map_address_that_is_not_http_with_a_host_is_refused(url: str) -> None:
    # bypass: refusal path; the named keys are its whole observable surface.
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"MAP_BASE_STYLE_URL": url})
    assert refused.value.setting_names == frozenset({"MAP_BASE_STYLE_URL"})


@given(host=_host, secret=_secret_value, part=st.sampled_from(["userinfo", "fragment"]))
def test_a_light_base_map_address_with_userinfo_or_a_fragment_is_refused_naming_the_part_but_never_its_value(
    host: str, secret: str, part: str
) -> None:
    userinfo = f"user:{secret}@" if part == "userinfo" else ""
    fragment = f"#{secret}" if part == "fragment" else ""
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"MAP_BASE_STYLE_URL": f"https://{userinfo}{host}/s.json{fragment}"})
    message = str(refused.value)
    assert refused.value.setting_names == frozenset({"MAP_BASE_STYLE_URL"})
    assert "MAP_BASE_STYLE_URL" in message and part in message
    assert secret not in message
    assert secret not in repr(refused.value) and secret not in repr(refused.value.__cause__)


@given(
    host=_host,
    word=_key_words,
    case=_case,
    before_word=st.from_regex(r"[a-z_]{0,6}", fullmatch=True),
    after_word=st.from_regex(r"[a-z_]{0,6}", fullmatch=True),
    value=_secret_value,
    other=st.sampled_from(["", "lang=it&", "v=2&"]),
)
def test_a_light_base_map_address_carrying_a_private_parameter_is_refused_naming_it_but_never_its_value(
    host: str, word: str, case: Any, before_word: str, after_word: str, value: str, other: str
) -> None:
    name = case(f"{before_word}{word}{after_word}")
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"MAP_BASE_STYLE_URL": f"https://{host}/s.json?{other}{name}={value}"})
    message = str(refused.value)
    assert refused.value.setting_names == frozenset({"MAP_BASE_STYLE_URL"})
    assert "MAP_BASE_STYLE_URL" in message and f"carries the private parameter {name}" in message
    assert value not in message
    assert value not in repr(refused.value) and value not in repr(refused.value.__cause__)


@given(
    host=_host,
    word=_key_words,
    case=_case,
    digits=st.from_regex(r"[0-9]{4,8}", fullmatch=True),
    setting=st.sampled_from(["MAP_TILE_URL", "MAP_BASE_STYLE_URL"]),
)
def test_a_bare_query_word_with_a_private_name_is_refused_without_echoing_it(
    host: str, word: str, case: Any, digits: str, setting: str
) -> None:
    # A bare `?mapkey123abcdef` may itself be the secret: the refusal says a private parameter, not which.
    bare = case(f"{word}{digits}")
    tail = "/{z}/{x}/{y}.png" if setting == "MAP_TILE_URL" else "/s.json"
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({setting: f"https://{host}{tail}?{bare}"})
    message = str(refused.value)
    assert refused.value.setting_names == frozenset({setting})
    assert "carries a private parameter" in message
    assert bare not in message and digits not in message
    assert digits not in repr(refused.value) and digits not in repr(refused.value.__cause__)


# ------------------------------------------------------------------ the served road map (slice 12c, D301, D314)
@given(directory=_path, tileset=_printable)
def test_the_served_road_map_settings_read_as_written_and_empty_is_unknown(directory: str, tileset: str) -> None:
    written = Settings.from_environ(
        {"ROAD_MAP_DIR": directory, "ROAD_MAP_CHANGES_DIR": directory, "ROAD_MAP_SERVED_TILESET": tileset}
    )
    assert (written.road_map_dir, written.road_map_changes_dir, written.road_map_served_tileset) == (
        Path(directory),
        Path(directory),
        tileset,
    )
    empty = Settings.from_environ({"ROAD_MAP_DIR": "", "ROAD_MAP_CHANGES_DIR": "", "ROAD_MAP_SERVED_TILESET": ""})
    assert (empty.road_map_dir, empty.road_map_changes_dir, empty.road_map_served_tileset) == (None, None, None)
    unset = Settings.from_environ({})
    assert (unset.road_map_dir, unset.road_map_served_tileset) == (None, None)


@given(tileset=_printable)
def test_a_served_tileset_named_for_the_offline_road_map_is_refused_with_valhalla(tileset: str) -> None:
    # bypass: refusal path; the error's named keys are its whole observable surface.
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"ROUTING_PROVIDER": "valhalla", "ROAD_MAP_SERVED_TILESET": tileset})
    assert refused.value.setting_names == frozenset({"ROAD_MAP_SERVED_TILESET"})
    assert "ROAD_MAP_SERVED_TILESET" in str(refused.value)
    assert Settings.from_environ({"ROUTING_PROVIDER": "mock", "ROAD_MAP_SERVED_TILESET": tileset})
    assert Settings.from_environ({"ROUTING_PROVIDER": "valhalla", "ROAD_MAP_SERVED_TILESET": ""})


# ------------------------------------------------------------------ place search (slice 12c, D307, D314 (3))
PLACE_DEFAULTS = {"PLACE_SEARCH": "on", "PLACE_SEARCH_URL": "https://nominatim.openstreetmap.org/search"}
PLACE_UNIVERSE = frozenset(PLACE_DEFAULTS)


def place_view(settings: Settings) -> dict[str, Any]:
    return {"PLACE_SEARCH": settings.place_search, "PLACE_SEARCH_URL": settings.place_search_url}


@given(key=st.sampled_from(sorted(PLACE_DEFAULTS)))
def test_an_empty_or_absent_place_search_setting_is_its_default(key: str) -> None:
    # compose passes `${KEY:-}`: an unset key arrives empty and means the default, which for PLACE_SEARCH is on.
    before = place_view(Settings.from_environ({}))
    after = place_view(Settings.from_environ({key: ""}))
    assert before == PLACE_DEFAULTS
    assert_state_delta(before, after, universe=PLACE_UNIVERSE, expected={k: unchanged() for k in PLACE_UNIVERSE})


@given(switch=st.sampled_from(["on", "off"]), address=_host.map(lambda host: f"https://{host}/search"))
def test_the_place_search_switch_and_address_are_taken_as_given(switch: str, address: str) -> None:
    after = place_view(Settings.from_environ({"PLACE_SEARCH": switch, "PLACE_SEARCH_URL": address}))
    assert after == {"PLACE_SEARCH": switch, "PLACE_SEARCH_URL": address}


@given(value=_printable.filter(lambda raw: raw not in {"on", "off"}))
def test_a_place_search_value_other_than_on_or_off_is_refused_naming_the_key_but_never_the_value(value: str) -> None:
    # bypass: a refusal leaves no settings to diff; the error's named keys and text are its whole observable surface.
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"PLACE_SEARCH": value})
    assert refused.value.setting_names == frozenset({"PLACE_SEARCH"})
    assert "PLACE_SEARCH" in str(refused.value)
    # the text is the same whatever was written, so the value is never in it
    with pytest.raises(InvalidSettingsError) as reference:
        Settings.from_environ({"PLACE_SEARCH": "~"})
    assert str(refused.value) == str(reference.value)


# ------------------------------------------------------------------ the region list (slice 12c, D306, D313 O3)
GEOFABRIK_DEFAULT = "https://download.geofabrik.de/index-v1-nogeom.json"


@pytest.mark.parametrize("environ", [{}, {"GEOFABRIK_INDEX_URL": ""}])
def test_an_empty_or_absent_region_list_address_is_the_public_default(environ: dict[str, str]) -> None:
    assert Settings.from_environ(environ).geofabrik_index_url == GEOFABRIK_DEFAULT


@given(address=_host.map(lambda host: f"http://{host}:8123/index-v1-nogeom.json"))
def test_the_region_list_address_is_taken_as_given(address: str) -> None:
    assert Settings.from_environ({"GEOFABRIK_INDEX_URL": address}).geofabrik_index_url == address


@pytest.mark.parametrize("value", ["download.geofabrik.de/index.json", "ftp://example.org/index.json", "https:///x"])
def test_a_region_list_address_that_is_not_http_with_a_host_is_refused_naming_the_key(value: str) -> None:
    with pytest.raises(InvalidSettingsError) as refused:
        Settings.from_environ({"GEOFABRIK_INDEX_URL": value})
    assert refused.value.setting_names == frozenset({"GEOFABRIK_INDEX_URL"})
