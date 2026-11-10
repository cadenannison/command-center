"""Shared iCalendar parsing for the CalDAV and iCal-feed adapters: text in, Events out.

Pure functions, no I/O. Both adapters hand over iCalendar text and get timezone-aware Events that
match what `EventStore.query(window)` would match (docs/contracts/adapters.md, rule 10).
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import cast
from urllib.parse import urlsplit

import recurring_ical_events  # pyright: ignore[reportMissingTypeStubs]
from icalendar import Calendar
from icalendar import Event as VEvent

from command_center.core.schema import Event, event_id
from command_center.core.windows import TimeWindow

NO_TITLE = "(no title)"
# Ranges are asked for wider than the window: a floating or all-day item is only placed on the
# timeline after localising in our tz, and a server matches it in the request's zone, so the two can
# disagree by up to a day. Callers filter exactly with events_in_window.
EXPANSION_PAD = timedelta(days=2)
_LINK_SCHEMES = ("http", "https")


def parse_calendar(data: bytes | str) -> Calendar:
    """Parse one iCalendar document; ValueError if it is not one. The message never quotes data."""
    parsed: object = None
    try:
        parsed = Calendar.from_ical(data)
    except Exception:  # noqa: BLE001  (untrusted text; the parser's errors may quote it)
        parsed = None
    if not isinstance(parsed, Calendar):
        msg = "Not an iCalendar document"
        raise ValueError(msg)  # noqa: TRY004  (a value problem, not a type problem)
    return parsed


def events_in_window(  # noqa: PLR0913  (a keyword-only parameter bundle, nothing to group)
    calendar: Calendar,
    *,
    source: str,
    scope: str,
    tz: tzinfo,
    window: TimeWindow,
    fetched_at: datetime,
    extra_raw: Mapping[str, object] | None = None,
) -> list[Event]:
    """Return the calendar's VEVENTs as Events, recurrences expanded, that match window.

    scope tells apart the same UID in two calendars or feeds; it is hashed into the id and is never
    stored. tz places floating times and all-day dates. A cancelled item is skipped. ValueError if
    the rules cannot be expanded; the message never quotes the calendar. An item with no
    DTSTART is dropped.
    """
    components: list[VEvent] | None = None
    # The expander raises on an item without DTSTART; with no time it can match no window anyway.
    calendar.subcomponents = [
        part for part in calendar.subcomponents if part.name != "VEVENT" or "DTSTART" in part
    ]
    try:
        components = cast(
            "list[VEvent]",
            recurring_ical_events.of(calendar).between(
                window.start - EXPANSION_PAD, window.end + EXPANSION_PAD
            ),
        )
    except Exception:  # noqa: BLE001  (untrusted rules; the library's errors may quote them)
        components = None
    if components is None:
        msg = "The calendar's recurrence rules could not be expanded"
        raise ValueError(msg)
    found: dict[str, Event] = {}
    for component in components:
        event = _to_event(
            component,
            source=source,
            scope=scope,
            tz=tz,
            window=window,
            fetched_at=fetched_at,
            extra_raw=extra_raw or {},
        )
        if event is not None:
            found[event.id] = event
    return list(found.values())


def _to_event(  # noqa: PLR0913
    component: VEvent,
    *,
    source: str,
    scope: str,
    tz: tzinfo,
    window: TimeWindow,
    fetched_at: datetime,
    extra_raw: Mapping[str, object],
) -> Event | None:
    status = _text(component, "STATUS")
    if status is not None and status.upper() == "CANCELLED":
        return None
    start = localise(component.start, tz)
    end = localise(component.end, tz)
    span_end = end if end > start else None
    if not _in_window(start, span_end, window):
        return None
    title = _text(component, "SUMMARY") or NO_TITLE
    uid = _text(component, "UID") or title
    start_utc = start.astimezone(UTC).isoformat()
    return Event(
        id=event_id(source, f"{scope}\x00{uid}\x00{start_utc}"),
        source=source,
        kind="event",
        title=title,
        start=start,
        end=span_end,
        link=_link(component),
        status=status.lower() if status else None,
        raw={"uid": uid, "location": _text(component, "LOCATION"), **extra_raw},
        fetched_at=fetched_at,
    )


def _in_window(start: datetime, end: datetime | None, window: TimeWindow) -> bool:
    """The store's rule: a span matches by overlap, a point by its start in [start, end)."""
    window_start = window.start.astimezone(UTC)
    window_end = window.end.astimezone(UTC)
    if end is not None:
        return start.astimezone(UTC) < window_end and end.astimezone(UTC) > window_start
    return window_start <= start.astimezone(UTC) < window_end


def localise(value: date | datetime, tz: tzinfo) -> datetime:
    """Aware datetimes pass through; floating ones and all-day dates are placed in tz."""
    if isinstance(value, datetime):
        return value if value.utcoffset() is not None else value.replace(tzinfo=tz)
    return datetime.combine(value, time.min, tzinfo=tz)


def _text(component: VEvent, name: str) -> str | None:
    value = component.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _link(component: VEvent) -> str | None:
    """The item's URL property, only if it is http(s): the UI renders it as a link."""
    url = _text(component, "URL")
    if url is None:
        return None
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return None
    return url if scheme in _LINK_SCHEMES else None
