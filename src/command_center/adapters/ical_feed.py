"""Pasted iCal feed URLs (BYU LearningSuite, one per course) as a source adapter."""

import asyncio
import hashlib
import logging
from collections.abc import Mapping
from datetime import tzinfo
from urllib.parse import urlsplit

import httpx
from icalendar import Calendar

from command_center.adapters.ical_events import events_in_window, parse_calendar
from command_center.adapters.net_guard import ensure_public_host
from command_center.core.errors import AuthExpired, FatalError, TransientError
from command_center.core.ports import Clock
from command_center.core.redact import redact
from command_center.core.schema import Event, ValidationResult
from command_center.core.urlcheck import require_https_public
from command_center.core.windows import TimeWindow

logger = logging.getLogger(__name__)

SOURCE_NAME = "learningsuite"
MAX_FEED_BYTES = 5 * 1024 * 1024
TIMEOUT_SECONDS = 10.0
_TRANSIENT_STATUSES = frozenset({408, 425, 429})
_OK = 200
_NOT_MODIFIED = 304
_UNAUTHORIZED = 401
_FORBIDDEN = 403
_REDIRECT_MIN = 300
_REDIRECT_MAX = 400
_SERVER_ERROR_MIN = 500


class IcalFeedAdapter:
    """Reads each feed URL in creds["urls"] (newline-separated); events only, never partial."""

    def __init__(self, tz: tzinfo, clock: Clock) -> None:
        self._tz = tz
        self._clock = clock
        self._cache: dict[str, tuple[str, bytes]] = {}

    @property
    def name(self) -> str:
        return SOURCE_NAME

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        urls = feed_urls(creds)
        if not urls:
            return ValidationResult(ok=False, message="Paste at least one feed URL")
        for number, url in enumerate(urls, start=1):
            try:
                await self._load(number, url)
            except (AuthExpired, FatalError) as exc:
                return ValidationResult(ok=False, message=str(exc))
        count = len(urls)
        return ValidationResult(
            ok=True, message=f"Connected {count} feed{'s' if count > 1 else ''}"
        )

    async def fetch(self, creds: Mapping[str, str], window: TimeWindow) -> list[Event]:
        urls = feed_urls(creds)
        if not urls:
            msg = "Failed to fetch LearningSuite feeds: no feed URLs are configured"
            raise FatalError(msg)
        fetched_at = self._clock.now()
        events: list[Event] = []
        in_feeds = 0
        for number, url in enumerate(urls, start=1):
            calendar = await self._load(number, url)
            in_feeds += sum(1 for part in calendar.subcomponents if part.name == "VEVENT")
            try:
                found = await asyncio.to_thread(
                    events_in_window,
                    calendar,
                    source=SOURCE_NAME,
                    scope=str(number),
                    tz=self._tz,
                    window=window,
                    fetched_at=fetched_at,
                    extra_raw={"feed": number},
                )
            except ValueError:
                msg = f"Feed {number}: a recurring item could not be expanded"
                raise FatalError(msg) from None
            events.extend(found)
        self._forget_unused(urls)
        if not events:
            note = zero_items_message(len(urls), in_feeds)
            logger.info(redact(note), extra={"source": SOURCE_NAME})
        return events

    async def _load(self, number: int, url: str) -> Calendar:
        body = await self._download(number, url)
        try:
            return await asyncio.to_thread(parse_calendar, body)
        except ValueError:
            msg = f"Feed {number}: the response is not an iCalendar feed"
            raise FatalError(msg) from None

    async def _download(self, number: int, url: str) -> bytes:
        await check_feed_url(number, url)
        key = hashlib.sha256(url.encode()).hexdigest()
        cached = self._cache.get(key)
        headers = {"Accept": "text/calendar, */*;q=0.1"}
        if cached is not None:
            headers["If-None-Match"] = cached[0]
        failure: str | None = None
        body = b""
        etag: str | None = None
        try:
            async with (
                asyncio.timeout(TIMEOUT_SECONDS),
                httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client,
                client.stream("GET", url, headers=headers) as response,
            ):
                _raise_for_status(number, response.status_code, has_cache=cached is not None)
                if response.status_code == _NOT_MODIFIED and cached is not None:
                    return cached[1]
                body = await read_feed_capped(number, response)
                etag = response.headers.get("etag")
        except TimeoutError:
            failure = "timed out"
        except httpx.HTTPError:
            failure = "could not be reached"
        if failure is not None:
            msg = f"Feed {number}: {failure}"
            raise TransientError(msg)
        if etag:
            self._cache[key] = (etag, body)
        else:
            self._cache.pop(key, None)
        return body

    def _forget_unused(self, urls: list[str]) -> None:
        live = {hashlib.sha256(url.encode()).hexdigest() for url in urls}
        for key in set(self._cache) - live:
            del self._cache[key]


def zero_items_message(feeds: int, events_in_feeds: int) -> str:
    """Counts only: why a sync of these feeds kept nothing (decision 0140)."""
    feed_word = "feed" if feeds == 1 else "feeds"
    event_word = "event" if events_in_feeds == 1 else "events"
    return (
        f"Synced 0 items: {feeds} {feed_word}, {events_in_feeds} {event_word} in the feeds, "
        "0 inside the window"
    )


def feed_urls(creds: Mapping[str, str]) -> list[str]:
    """The stored feed URLs: one per line, blanks ignored."""
    return [line.strip() for line in creds.get("urls", "").splitlines() if line.strip()]


async def check_feed_url(number: int, url: str) -> None:
    """SSRF checks; the URL is a secret so no message quotes it."""
    rejected = False
    host: str | None = None
    try:
        require_https_public(url)
        host = urlsplit(url).hostname
    except ValueError:
        rejected = True
    if rejected or host is None:
        msg = f"Feed {number}: the URL is not a public https address"
        raise FatalError(msg)
    resolved_private = False
    lookup_timed_out = False
    try:
        await ensure_public_host(host)
    except ValueError:
        resolved_private = True
    except TransientError:
        lookup_timed_out = True
    if resolved_private:
        msg = f"Feed {number}: the host is not a public address"
        raise FatalError(msg)
    if lookup_timed_out:
        msg = f"Feed {number}: host lookup timed out"
        raise TransientError(msg)


def _raise_for_status(number: int, status: int, *, has_cache: bool) -> None:
    prefix = f"Feed {number}"
    if status == _NOT_MODIFIED and has_cache:
        return
    if _REDIRECT_MIN <= status < _REDIRECT_MAX:
        msg = f"{prefix}: the URL redirects ({status}); redirects are not followed"
        raise FatalError(msg)
    if status in (_UNAUTHORIZED, _FORBIDDEN):
        msg = f"{prefix}: access was refused ({status}); paste the feed URL again"
        raise AuthExpired(msg)
    if status in _TRANSIENT_STATUSES or status >= _SERVER_ERROR_MIN:
        msg = f"{prefix}: the server returned {status}"
        raise TransientError(msg)
    if status != _OK:
        msg = f"{prefix}: the server returned {status}"
        raise FatalError(msg)


async def read_feed_capped(number: int, response: httpx.Response) -> bytes:
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_FEED_BYTES:
        msg = f"Feed {number}: larger than {MAX_FEED_BYTES // (1024 * 1024)} MB"
        raise FatalError(msg)
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_FEED_BYTES:
            msg = f"Feed {number}: larger than {MAX_FEED_BYTES // (1024 * 1024)} MB"
            raise FatalError(msg)
    return bytes(body)
