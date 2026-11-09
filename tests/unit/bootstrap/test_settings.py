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
)
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
    "ROUTING_PROVIDER": st.just(("mock", "mock")),
    "SOLVER_BUDGET": st.integers(min_value=1, max_value=10**7).map(lambda n: (str(n), n)),
    "PLANNER_GIT_SHA": _printable.map(lambda raw: (raw, raw)),
    "WEB_DIST_DIR": _path.map(lambda raw: (raw, Path(raw))),
    "MIGRATIONS_DIR": _path.map(lambda raw: (raw, Path(raw))),
    "PLANNER_BASIC_AUTH_USER": st.text(_secret_char.filter(lambda c: c != ":"), min_size=1).map(lambda raw: (raw, raw)),
    "PLANNER_BASIC_AUTH_PASSWORD": st.text(_secret_char, min_size=1).map(lambda raw: (raw, raw)),
    **{cap: st.integers(min_value=1, max_value=10**4).map(lambda n: (str(n), n)) for cap in UPLOAD_CAPS},
}

INVALID: dict[str, st.SearchStrategy[str]] = {
    "DATA_DIR": st.just(""),
    "LOG_LEVEL": _printable.filter(lambda raw: raw not in {"DEBUG", "INFO", "WARNING", "ERROR"}),
    "ROUTING_PROVIDER": _printable.filter(lambda raw: raw != "mock"),
    "SOLVER_BUDGET": st.integers(max_value=0).map(str) | st.from_regex(r"[A-Za-z]{1,8}", fullmatch=True),
    "PLANNER_GIT_SHA": st.just(""),
    "WEB_DIST_DIR": st.just(""),
    "MIGRATIONS_DIR": st.just(""),
    # RFC 7617: the user part of Basic credentials ends at the first colon, so such a user could never log in.
    "PLANNER_BASIC_AUTH_USER": st.tuples(st.text(max_size=5), st.text(max_size=5)).map(lambda p: f"{p[0]}:{p[1]}"),
    **{cap: st.integers(max_value=0).map(str) | st.from_regex(r"[A-Za-z]{1,8}", fullmatch=True) for cap in UPLOAD_CAPS},
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


@given(provider=_printable.filter(lambda raw: raw != "mock"))
def test_invalid_routing_provider_is_refused(provider: str) -> None:
    # bypass: refusal path, see above. Only `mock` is accepted before slice 06a wires Valhalla.
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
