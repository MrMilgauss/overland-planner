"""Settings parsing properties (driving port: `Settings.from_environ`, the composition root's config gate).

Universe = the six settings the planner reads (brief section 12 keys + WEB_DIST_DIR), named by their environment key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from overland_planner.bootstrap.settings import InvalidSettingsError, Settings
from tests.common.state_delta import assert_state_delta, set_to, unchanged

KEYS = ("DATA_DIR", "LOG_LEVEL", "ROUTING_PROVIDER", "SOLVER_BUDGET", "PLANNER_GIT_SHA", "WEB_DIST_DIR")
UNIVERSE = set(KEYS)

_segment = st.from_regex(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,11}", fullmatch=True)
_path = st.lists(_segment, min_size=1, max_size=4).map(lambda parts: "/" + "/".join(parts))
_printable = st.text(st.characters(min_codepoint=33, max_codepoint=126), min_size=1, max_size=40)

# Raw environment text -> the value the planner must see for it.
VALID: dict[str, st.SearchStrategy[tuple[str, Any]]] = {
    "DATA_DIR": _path.map(lambda raw: (raw, Path(raw))),
    "LOG_LEVEL": st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR"]).map(lambda raw: (raw, raw)),
    "ROUTING_PROVIDER": st.just(("mock", "mock")),
    "SOLVER_BUDGET": st.integers(min_value=1, max_value=10**7).map(lambda n: (str(n), n)),
    "PLANNER_GIT_SHA": _printable.map(lambda raw: (raw, raw)),
    "WEB_DIST_DIR": _path.map(lambda raw: (raw, Path(raw))),
}

INVALID: dict[str, st.SearchStrategy[str]] = {
    "DATA_DIR": st.just(""),
    "LOG_LEVEL": _printable.filter(lambda raw: raw not in {"DEBUG", "INFO", "WARNING", "ERROR"}),
    "ROUTING_PROVIDER": _printable.filter(lambda raw: raw != "mock"),
    "SOLVER_BUDGET": st.integers(max_value=0).map(str) | st.from_regex(r"[A-Za-z]{1,8}", fullmatch=True),
    "PLANNER_GIT_SHA": st.just(""),
    "WEB_DIST_DIR": st.just(""),
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
    }


@st.composite
def environments(draw: st.DrawFn) -> tuple[dict[str, str], dict[str, Any]]:
    """A process environment with any subset of the planner's keys set to valid values, plus unrelated keys."""
    chosen = draw(st.lists(st.sampled_from(KEYS), unique=True))
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


@given(data=st.data(), key=st.sampled_from(KEYS))
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
