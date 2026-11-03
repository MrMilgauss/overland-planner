"""Optional shared household password (brief §12, ADR-011 Amendment 1, D98): HTTP Basic auth around the whole app.

Every path is guarded (web page, static assets, the API, /api/health) except the liveness check `/healthz`, which
reveals no project data. User and password are compared with `secrets.compare_digest` on their UTF-8 bytes, so
prefixes, case changes and other Unicode normal forms are refused. A refused /api request gets the error envelope
`{code: unauthorized, message}` (brief §5); any other path a plain 401. Both carry `WWW-Authenticate: Basic`.
The Authorization header is never logged or echoed.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from dataclasses import dataclass

from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from overland_planner.adapters.http.errors import envelope

OPEN_PATH = "/healthz"
CHALLENGE = {"WWW-Authenticate": 'Basic realm="Overland Route Planner", charset="UTF-8"'}
_MESSAGE = "Log in with the shared household password"


@dataclass(frozen=True, repr=False)
class BasicAuthCredentials:
    user: str
    password: str

    def admit(self, authorization: bytes | None) -> bool:
        """True iff the header carries Basic credentials with exactly this user and password."""
        scheme, _, token = (authorization or b"").partition(b" ")
        if scheme.lower() != b"basic":
            return False
        try:
            decoded = base64.b64decode(token.strip(), validate=True)
        except (binascii.Error, ValueError):
            return False
        user, colon, password = decoded.partition(b":")
        user_ok = secrets.compare_digest(user, self.user.encode())
        password_ok = secrets.compare_digest(password, self.password.encode())
        return bool(colon) and user_ok and password_ok


class BasicAuthMiddleware:
    """Pure ASGI middleware: answers 401 before the request reaches any route or the web page."""

    def __init__(self, app: ASGIApp, *, credentials: BasicAuthCredentials) -> None:
        self._app = app
        self._credentials = credentials

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == OPEN_PATH:
            await self._app(scope, receive, send)
            return
        authorization = dict(scope["headers"]).get(b"authorization")
        if self._credentials.admit(authorization):
            await self._app(scope, receive, send)
            return
        await _refusal(scope["path"])(scope, receive, send)


def _refusal(path: str) -> Response:
    if path == "/api" or path.startswith("/api/"):
        refused = envelope(401, "unauthorized", _MESSAGE)
        refused.headers.update(CHALLENGE)
        return refused
    return PlainTextResponse("Unauthorized", status_code=401, headers=CHALLENGE)
