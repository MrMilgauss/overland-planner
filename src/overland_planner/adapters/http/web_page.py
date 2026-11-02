"""The built web page (D162): `WEB_DIST_DIR` served at `/`, mounted after the API and health routes.

Without a build (no `index.html`) nothing is mounted, so `/` answers 404: there is no placeholder page.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_web_page(app: FastAPI, web_dist_dir: Path) -> None:
    if (web_dist_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dist_dir, html=True), name="web")
