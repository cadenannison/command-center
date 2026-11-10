"""Counts-only diagnosis of the stored iCal feeds ("why does LearningSuite return 0 items").

Everything this module returns or renders is a count, a category or a date. No URL, host, title,
description, location or credential is ever put in a report or in its text: the feed URL is a
secret (decision 0005) and a title is personal data. Problems are fixed phrases, never the text of
an exception, because an exception from a library may quote the input.
"""

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, tzinfo
from typing import Literal

import httpx
from icalendar import Calendar, Component

from command_center.adapters.ical_diagnose_report import FeedReport
from command_center.adapters.ical_events import events_in_window, localise, parse_calendar
from command_center.adapters.ical_feed import (
    MAX_FEED_BYTES,
    SOURCE_NAME,
    TIMEOUT_SECONDS,
    check_feed_url,
    read_feed_capped,
)
from command_center.core.errors import FatalError, TransientError
from command_center.core.urlcheck import require_https_public
from command_center.core.windows import TimeWindow

logger = logging.getLogger(__name__)

type Bucket = Literal["inside", "before", "after", "undated", "cancelled", "dropped"]
_OK_MIN = 200
_OK_MAX = 300
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})


def content_kind(content_type: str | None) -> str:
    """A coarse kind for a Content-Type header: the header itself is never reported."""
    if not content_type:
        return "missing"
    media = content_type.split(";", 1)[0].strip().lower()
    if media == "text/calendar":
        return "calendar"
    if media in _HTML_TYPES:
        return "html"
    if media == "text/plain":
        return "text"
    if media == "application/json" or media.endswith("+json"):
        return "json"
    return "other"


def status_class(status: int) -> str:
    """1xx..5xx; anything else is "other"."""
    return f"{status // 100}xx" if 100 <= status < 600 else "other"  # noqa: PLR2004


async def diagnose_feeds(urls: list[str], tz: tzinfo, window: TimeWindow) -> list[FeedReport]:
    """Download and analyse each feed in turn; one unreadable feed does not stop the others."""
    return [await _diagnose_one(number, url, tz, window) for number, url in enumerate(urls, 1)]


async def _diagnose_one(number: int, url: str, tz: tzinfo, window: TimeWindow) -> FeedReport:
    try:
        return await _diagnose_checked(number, url, tz, window)
    except Exception as exc:  # noqa: BLE001  (a fixed phrase: the text of a library error may quote the URL)
        logger.warning("feed diagnosis failed: %s", type(exc).__name__)
        return FeedReport(number=number, problem="an unexpected error stopped the check")


async def _diagnose_checked(number: int, url: str, tz: tzinfo, window: TimeWindow) -> FeedReport:
    rejected: str | None = None
    try:
        await check_feed_url(number, url)
    except FatalError:
        rejected = _rejection(url)
    except TransientError:
        rejected = "host lookup timed out"
    if rejected is not None:
        return FeedReport(number=number, problem=rejected)
    probe = await _probe(url)
    if probe.problem is not None or probe.body is None:
        return FeedReport(
            number=number,
            problem=probe.problem,
            status_class=probe.status_class,
            content_kind=probe.content_kind,
            size_bytes=probe.size_bytes,
        )
    analysed = await asyncio.to_thread(_analyse, number, probe.body, tz, window)
    return replace(
        analysed,
        status_class=probe.status_class,
        content_kind=probe.content_kind,
        size_bytes=probe.size_bytes,
    )


def _rejection(url: str) -> str:
    """Tell a malformed or non-https URL from a host that is private or does not resolve."""
    try:
        require_https_public(url)
    except ValueError:
        return "the URL is not a public https address"
    return "the host is not a public address or could not be resolved"


@dataclass(frozen=True, slots=True)
class _Probe:
    problem: str | None
    status_class: str | None = None
    content_kind: str | None = None
    size_bytes: int | None = None
    body: bytes | None = None


async def _probe(url: str) -> _Probe:
    """One GET without following redirects; the body is read only for a 2xx answer."""
    failure: str | None = None
    result = _Probe(problem="could not be reached")
    try:
        async with (
            asyncio.timeout(TIMEOUT_SECONDS),
            httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client,
            client.stream("GET", url, headers={"Accept": "text/calendar, */*;q=0.1"}) as response,
        ):
            code = response.status_code
            kind = content_kind(response.headers.get("content-type"))
            if not _OK_MIN <= code < _OK_MAX:
                return _Probe(
                    problem="the server did not return the feed",
                    status_class=status_class(code),
                    content_kind=kind,
                )
            try:
                body = await read_feed_capped(0, response)
            except FatalError:
                failure = f"larger than {MAX_FEED_BYTES // (1024 * 1024)} MB"
            else:
                result = _Probe(
                    problem=None,
                    status_class=status_class(code),
                    content_kind=kind,
                    size_bytes=len(body),
                    body=body,
                )
    except TimeoutError:
        result = _Probe(problem="timed out")
    except httpx.HTTPError:
        result = _Probe(problem="could not be reached")
    if failure is not None:
        return _Probe(problem=failure, status_class="2xx")
    return result


def _analyse(number: int, body: bytes, tz: tzinfo, window: TimeWindow) -> FeedReport:
    try:
        calendar = parse_calendar(body)
    except ValueError:
        return FeedReport(number=number, problem="the response is not an iCalendar feed")
    parts = list(calendar.subcomponents)
    zones = [part for part in parts if part.name == "VTIMEZONE"]
    events = [part for part in parts if part.name == "VEVENT"]
    todos = [part for part in parts if part.name == "VTODO"]
    counts: dict[Bucket, int] = dict.fromkeys(
        ("inside", "before", "after", "undated", "cancelled", "dropped"), 0
    )
    points: list[datetime] = []
    for group in _by_uid(events):
        for event in group:
            start = _point(event, "DTSTART")
            if start is not None:
                points.append(localise(start, tz))
        counts[_bucket(group, zones, tz, window)] += len(group)
    todos_dated = todos_inside = 0
    for todo in todos:
        due = _point(todo, "DUE") or _point(todo, "DTSTART")
        if due is None:
            continue
        moment = localise(due, tz)
        points.append(moment)
        todos_dated += 1
        todos_inside += window.start <= moment < window.end
    dates = [point.astimezone(tz).date() for point in points]
    return FeedReport(
        number=number,
        events=len(events),
        todos=len(todos),
        dated=len(events) - counts["undated"] + todos_dated,
        earliest=min(dates, default=None),
        latest=max(dates, default=None),
        inside=counts["inside"],
        before=counts["before"],
        after=counts["after"],
        undated=counts["undated"],
        cancelled=counts["cancelled"],
        dropped=counts["dropped"],
        todos_dated=todos_dated,
        todos_inside=todos_inside,
    )


def _by_uid(events: list[Component]) -> list[list[Component]]:
    """A recurring item and its RECURRENCE-ID overrides share a UID and are judged together."""
    groups: dict[str, list[Component]] = {}
    for number, event in enumerate(events):
        uid = str(event.get("UID", "")).strip()
        groups.setdefault(uid or f"no-uid-{number}", []).append(event)
    return list(groups.values())


def _bucket(
    group: list[Component], zones: list[Component], tz: tzinfo, window: TimeWindow
) -> Bucket:
    """Where one item (a VEVENT and its overrides) lands, by the adapter's own rule.

    The group goes through `events_in_window` as a calendar of its own, so an override that moves
    or cancels an instance counts as it would in a sync; every VEVENT of the group is counted
    under the group's bucket.
    """
    starts = [start for event in group if (start := _point(event, "DTSTART")) is not None]
    if not starts:
        return "undated"
    if all(str(event.get("STATUS", "")).strip().upper() == "CANCELLED" for event in group):
        return "cancelled"
    alone = Calendar()
    for part in (*zones, *group):
        alone.add_component(part)
    try:
        found = events_in_window(
            alone,
            source=SOURCE_NAME,
            scope="diagnose",
            tz=tz,
            window=window,
            fetched_at=window.start,
        )
    except ValueError:
        return "dropped"
    if found:
        return "inside"
    return "before" if localise(min(starts), tz) < window.start else "after"


def _point(component: Component, name: str) -> date | None:
    value = getattr(component.get(name), "dt", None)
    return value if isinstance(value, date) else None
