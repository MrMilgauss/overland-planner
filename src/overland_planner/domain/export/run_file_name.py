"""The file name of an exported plan run (US-02b). Pure domain.

Accents fold to ASCII, letters lowercase, and every run of anything else becomes one hyphen, so no project name can
reach a header or a path as anything but `[a-z0-9-]`. A name with nothing usable falls back to `plan`. The project part
is cut so the whole name fits the 255 bytes of common file systems: nothing limits how long a project name is.
"""

from __future__ import annotations

import re
import unicodedata

_ANYTHING_ELSE = re.compile(r"[^a-z0-9]+")
_FALLBACK = "plan"
_LONGEST_PROJECT_PART = 200
_ESTIMATE = "-estimate"


def run_file_name(project_name: str, run_number: int, *, estimate: bool = False) -> str:
    """`<project>-run<N>.gpx`, or `<project>-run<N>-estimate.gpx` for a plan on the offline road map (D268)."""
    return f"{_project_part(project_name)}-run{run_number}{_ESTIMATE if estimate else ''}.gpx"


def _project_part(project_name: str) -> str:
    hyphenated = _ANYTHING_ELSE.sub("-", _without_accents(project_name).lower())
    return hyphenated[:_LONGEST_PROJECT_PART].strip("-") or _FALLBACK


def _without_accents(text: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKD", text) if not unicodedata.combining(character)
    )
