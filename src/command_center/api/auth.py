"""Who needs a token: the Host header decides.

Tailscale Serve proxies the phone's request to 127.0.0.1, so the peer address is loopback for
the phone and for the web UI alike and cannot tell them apart. The `Host` header can: the
browser UI is opened at `localhost` or `127.0.0.1`, and a request that came through Serve
carries the tailnet name. So:

- a loopback Host keeps working with no token (the web UI), unless the request also carries
  proxy headers (`core.hosts`): a tailnet peer can choose its own Host, and Serve adds
  `X-Forwarded-*` / `Tailscale-*` headers that a direct local request does not have;
- any other host listed in `CC_ALLOWED_HOSTS` needs a valid device access token on every route
  except the open paths below;
- any other Host is refused with 400, whatever else the request carries (DNS rebinding).

This is an ASGI middleware, not a route dependency, so no route (the web pages, static files,
docs, a path that does not exist) can be added without it.
"""

import logging
from collections.abc import Sequence
from typing import cast

from fastapi import FastAPI
from fastapi.security import HTTPBearer
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from command_center.core.hosts import Exposure, classify_request
from command_center.services.container import Container

_POLICY_VIOLATION = 1008
logger = logging.getLogger(__name__)

# Reachable from the tailnet without a token: liveness, and the two calls that create one.
OPEN_PATHS = frozenset({"/v1/health", "/v1/pair", "/v1/pair/refresh"})
MAX_TOKEN_CHARS = 200

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="DeviceToken",
    description=(
        "A device access token from POST /v1/pair or /v1/pair/refresh. Required when the Host is "
        "the tailnet name; the Mac's own loopback web UI needs none."
    ),
)


def _bearer_token(headers: list[tuple[bytes, bytes]]) -> str | None:
    """The token of the one Authorization header, or None if it is missing, doubled or odd."""
    values = [value for name, value in headers if name.lower() == b"authorization"]
    if len(values) != 1:
        return None
    scheme, _, token = values[0].decode("latin-1").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > MAX_TOKEN_CHARS:
        return None
    return token


class DeviceAuthMiddleware:
    """Refuses requests per the module docstring. Fails closed when pairing is not wired."""

    def __init__(self, app: ASGIApp, fastapi_app: FastAPI, remote_hosts: Sequence[str]) -> None:
        self._app = app
        self._fastapi_app = fastapi_app
        self._remote_hosts = frozenset(host.lower() for host in remote_hosts)

    def _container(self) -> Container | None:
        return cast("Container | None", getattr(self._fastapi_app.state, "container", None))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        headers = cast("list[tuple[bytes, bytes]]", scope["headers"])
        host = next((v.decode("latin-1") for n, v in headers if n.lower() == b"host"), None)
        names = [name.decode("latin-1") for name, _ in headers]
        exposure = classify_request(host, names, self._remote_hosts)
        if exposure is Exposure.REJECTED:
            await _refuse(
                PlainTextResponse("Invalid host header", status_code=400), scope, receive, send
            )
            return
        needs_token = exposure is Exposure.REMOTE and scope["path"] not in OPEN_PATHS
        if needs_token and not await self._has_valid_token(headers):
            logger.warning("request refused: no valid device token", extra={"reason": "no_token"})
            response = JSONResponse(
                {"detail": "A valid device token is required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )
            await _refuse(response, scope, receive, send)
            return
        await self._app(scope, receive, send)

    async def _has_valid_token(self, headers: list[tuple[bytes, bytes]]) -> bool:
        token = _bearer_token(headers)
        container = self._container()
        if token is None or container is None or container.pairing is None:
            return False
        pairing = container.pairing
        return await run_in_threadpool(pairing.authenticate, token) is not None


async def _refuse(response: Response, scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": _POLICY_VIOLATION})
        return
    await response(scope, receive, send)


def install_auth(
    app: FastAPI, container: Container | None = None, *, remote_hosts: Sequence[str] = ()
) -> None:
    """Put the Host-and-token check in front of every route of `app`.

    `remote_hosts` are the non-loopback names to serve (the tailnet name). The container is read
    from `app.state.container` when the request arrives, so a factory-built container works; pass
    `container` to set it now.
    """
    if container is not None:
        app.state.container = container
    app.add_middleware(DeviceAuthMiddleware, fastapi_app=app, remote_hosts=tuple(remote_hosts))
