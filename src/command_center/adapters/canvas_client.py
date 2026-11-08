"""Canvas REST transport: bearer auth, Link pagination, rate-limit backoff, error translation."""

import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any
from urllib.parse import urlsplit

import httpx

from command_center.adapters.net_guard import ensure_public_host
from command_center.core.errors import AuthExpired, FatalError, TransientError
from command_center.core.urlcheck import require_https_public

logger = logging.getLogger(__name__)

type Sleep = Callable[[float], Awaitable[None]]
type Params = Mapping[str, str | list[str]]

PER_PAGE = 100
REQUEST_TIMEOUT = httpx.Timeout(15.0)
MAX_RATE_LIMIT_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0
LOW_QUOTA_REMAINING = 50.0
LOW_QUOTA_PAUSE_SECONDS = 2.0
MAX_PAGES = 200
_HTTPS_PORT = 443


def missing_credentials(creds: Mapping[str, str]) -> str | None:
    """Return a message naming what is missing from creds, or None if both keys are present."""
    if not creds.get("base_url", "").strip() or not creds.get("token", ""):
        return "Canvas needs both a base URL and an access token"
    return None


class CanvasClient:
    """Authenticated GETs against one checked Canvas origin; every call has a timeout."""

    def __init__(self, http: httpx.AsyncClient, origin: str, sleep: Sleep) -> None:
        self._http = http
        self._origin = origin
        self._sleep = sleep

    @property
    def origin(self) -> str:
        """The checked scheme://host[:port] every request goes to."""
        return self._origin

    async def get(self, path: str) -> httpx.Response:
        """GET one path with rate-limit backoff; raise a core error unless the status is 2xx."""
        return await self._get(f"{self._origin}{path}", None)

    async def pages(self, path: str, params: Params | None = None) -> list[Any]:
        """Return every item of a paginated list, following Link rel="next" until it ends."""
        url = f"{self._origin}{path}"
        query: Params | None = {"per_page": str(PER_PAGE), **(params or {})}
        seen = {url}
        items: list[Any] = []
        for _ in range(MAX_PAGES):
            response = await self._get(url, query)
            items.extend(_json_list(response))
            next_url = response.links.get("next", {}).get("url")
            if next_url is None:
                return items
            if not self._is_own_origin(next_url):
                msg = "Failed to fetch Canvas data: pagination link leaves the Canvas host"
                raise FatalError(msg)
            if next_url in seen:
                msg = "Failed to fetch Canvas data: pagination link repeats a page"
                raise FatalError(msg)
            seen.add(next_url)
            url, query = next_url, None
        msg = f"Failed to fetch Canvas data: more than {MAX_PAGES} pages"
        raise FatalError(msg)

    async def _get(self, url: str, params: Params | None) -> httpx.Response:
        attempt = 0
        while True:
            response = await self._send(url, params)
            if response.status_code in (403, 429):
                if attempt >= MAX_RATE_LIMIT_RETRIES:
                    msg = (
                        f"Failed to fetch Canvas data: rate limited ({response.status_code}) "
                        f"after {MAX_RATE_LIMIT_RETRIES} retries"
                    )
                    raise TransientError(msg)
                delay = _retry_delay(response, attempt)
                attempt += 1
                logger.warning(
                    "canvas rate limited, retry %d in %.0fs",
                    attempt,
                    delay,
                    extra={
                        "source": "canvas",
                        "attempt": attempt,
                        "delay_seconds": delay,
                        "reason": f"rate_limited_{response.status_code}",
                    },
                )
                await self._sleep(delay)
                continue
            _raise_for_status(response)
            if _quota_is_low(response):
                logger.warning(
                    "canvas quota low, pausing %.0fs",
                    LOW_QUOTA_PAUSE_SECONDS,
                    extra={"source": "canvas", "reason": "quota_low"},
                )
                await self._sleep(LOW_QUOTA_PAUSE_SECONDS)
            return response

    async def _send(self, url: str, params: Params | None) -> httpx.Response:
        try:
            return await self._http.get(url, params=params)
        except httpx.TimeoutException as exc:
            msg = "Failed to reach Canvas: the request timed out"
            raise TransientError(msg) from exc
        except httpx.InvalidURL as exc:
            msg = "Failed to fetch Canvas data: the request URL is invalid"
            raise FatalError(msg) from exc
        except httpx.HTTPError as exc:
            msg = f"Failed to reach Canvas: {type(exc).__name__}"
            raise TransientError(msg) from exc

    def _is_own_origin(self, url: str) -> bool:
        # The bearer token rides on every request, so it must never be sent to another host.
        try:
            return _origin_key(url) == _origin_key(self._origin)
        except ValueError:
            # A port out of range or a broken IPv6 literal cannot be our host.
            return False


@asynccontextmanager
async def open_canvas(creds: Mapping[str, str], sleep: Sleep) -> AsyncGenerator[CanvasClient]:
    """Check the base URL and its host, then yield a client bound to that origin.

    Raises AuthExpired if creds are incomplete, FatalError for an unusable URL and TransientError
    if the host lookup times out.
    """
    problem = missing_credentials(creds)
    if problem is not None:
        raise AuthExpired(problem)
    origin = await _checked_origin(creds["base_url"].strip())
    # follow_redirects stays off: a redirect could carry the token to another host.
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=False,
        headers={"Authorization": f"Bearer {creds['token']}", "Accept": "application/json"},
    ) as http:
        yield CanvasClient(http, origin, sleep)


async def _checked_origin(base_url: str) -> str:
    try:
        require_https_public(base_url)
        parts = urlsplit(base_url)
        # hostname is set: require_https_public rejects a URL without one.
        await ensure_public_host(str(parts.hostname))
    except ValueError as exc:
        msg = f"Invalid Canvas URL: {exc}"
        raise FatalError(msg) from None
    return f"https://{parts.netloc.lower()}"


def _origin_key(url: str) -> tuple[str, str | None, int]:
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.hostname, parts.port or _HTTPS_PORT


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    try:
        advised = float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        advised = BACKOFF_BASE_SECONDS * 2**attempt
    return min(max(advised, 0.0), MAX_BACKOFF_SECONDS)


def _quota_is_low(response: httpx.Response) -> bool:
    try:
        return float(response.headers["X-Rate-Limit-Remaining"]) < LOW_QUOTA_REMAINING
    except (KeyError, ValueError):
        return False


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status == HTTPStatus.UNAUTHORIZED:
        msg = "Failed to fetch Canvas data: token rejected (401)"
        raise AuthExpired(msg)
    if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        msg = f"Failed to fetch Canvas data: Canvas server error ({status})"
        raise TransientError(msg)
    if not response.is_success:
        msg = f"Failed to fetch Canvas data: unexpected status ({status})"
        raise FatalError(msg)


def _json_list(response: httpx.Response) -> list[Any]:
    try:
        body: Any = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = None
    if not isinstance(body, list):
        msg = "Failed to fetch Canvas data: response was not a JSON list"
        raise FatalError(msg)
    return body  # pyright: ignore[reportUnknownVariableType]
