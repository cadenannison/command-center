"""Reads upcoming items from the menu-bar app's own server over loopback HTTP."""

from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx
from pydantic import TypeAdapter, ValidationError

from command_center.core.schema import Event

_TIMEOUT = httpx.Timeout(5.0)
_LOOPBACK = frozenset({"127.0.0.1", "localhost"})
_EVENTS = TypeAdapter(list[Event])


class ServerUnavailableError(Exception):
    """The local server did not answer usefully."""


class LocalServerClient:
    """A tiny client for the local server. It refuses any base URL that is not loopback."""

    def __init__(self, base_url: str) -> None:
        parts = urlsplit(base_url)
        if parts.scheme != "http" or parts.hostname not in _LOOPBACK:
            msg = "the local server client only talks to a loopback http URL"
            raise ValueError(msg)
        self._base_url = base_url.rstrip("/")

    def upcoming(self, now: datetime, window: timedelta) -> list[Event]:
        """Events between now and now + window."""
        params = {"from": now.isoformat(), "to": (now + window).isoformat()}
        try:
            response = httpx.get(f"{self._base_url}/v1/events", params=params, timeout=_TIMEOUT)
            response.raise_for_status()
            return _EVENTS.validate_python(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as error:
            msg = f"the local server did not return events: {type(error).__name__}"
            raise ServerUnavailableError(msg) from error

    def healthy(self) -> bool:
        """Whether the health route answers."""
        try:
            return httpx.get(f"{self._base_url}/v1/health", timeout=_TIMEOUT).is_success
        except httpx.HTTPError:
            return False
