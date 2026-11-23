"""Static bearer-token auth for the HTTP app (MCP endpoint and /reindex*).

A pure-ASGI middleware rather than Starlette's `BaseHTTPMiddleware`, which buffers
response bodies and would stall the streamed NDJSON and SSE responses.
"""

from __future__ import annotations

import hmac
import json

from starlette.types import ASGIApp, Receive, Scope, Send

_UNAUTHORIZED_BODY = json.dumps({"error": "unauthorized"}).encode()


class BearerTokenMiddleware:
    """Require `Authorization: Bearer <token>` on every HTTP and WebSocket request."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        if not token:
            raise ValueError("BearerTokenMiddleware requires a non-empty token")
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Lifespan (and anything else that isn't a client request) passes through.
        if scope["type"] not in ("http", "websocket") or self._authorized(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            # Close before accept; the ASGI server answers the handshake with 403.
            await send({"type": "websocket.close", "code": 1008})
            return
        await _send_unauthorized(send)

    def _authorized(self, scope: Scope) -> bool:
        header = _get_header(scope, b"authorization")
        if header is None:
            return False
        scheme, _, credentials = header.partition(b" ")
        if scheme.lower() != b"bearer":
            return False
        credentials = credentials.strip()
        return bool(credentials) and hmac.compare_digest(credentials, self._token)


def _get_header(scope: Scope, name: bytes) -> bytes | None:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            return value
    return None


async def _send_unauthorized(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_UNAUTHORIZED_BODY)).encode()),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})
