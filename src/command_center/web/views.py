"""Turns scored events into what the templates draw. Pure: no I/O, no clock, no service calls."""

import calendar
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from urllib.parse import urlsplit

from command_center.core.ledger import ItemMark
from command_center.core.schema import Event
from command_center.core.scoring import explain
from command_center.services.agenda import ATTENTION_URGENCY
from command_center.web.item_view import ItemControls, item_controls

HEAT_LEVELS = 4
TOP_DEADLINES = 8
_DONE = "done"
_LINK_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class Row:
    """One line in an agenda, a column or a list."""

    title: str
    when: str
    kind: str
    urgency: int
    urgent: bool
    status: str | None = None
    link: str | None = None
    # 1-10, or None for a done or ended item (core/priority.py).
    priority: int | None = None
    # Why the item has its priority ("Due in 18 hours, not submitted"); "" when no `now` was given.
    reason: str = ""
    # The check-off, note and task controls; None when the container has no item service.
    item: ItemControls | None = None


@dataclass(frozen=True)
class DayColumn:
    """One day of the week view. `load` is the sum of its items' urgency."""

    day: date
    label: str
    is_today: bool
    load: int
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class MonthCell:
    """One day of the month grid; `level` is 0 (empty) to HEAT_LEVELS (busiest day)."""

    day: date
    in_month: bool
    is_today: bool
    load: int
    count: int
    level: int


@dataclass(frozen=True)
class TodayView:
    """The Today page without the summary."""

    day: date
    title: str
    agenda: tuple[Row, ...]
    weather: tuple[Row, ...]
    attention: tuple[Row, ...]
    previous: date
    next: date


@dataclass(frozen=True)
class WeekView:
    """The Week page."""

    title: str
    columns: tuple[DayColumn, ...]
    previous: date
    next: date


@dataclass(frozen=True)
class MonthView:
    """The Month page."""

    title: str
    weeks: tuple[tuple[MonthCell, ...], ...]
    deadlines: tuple[Row, ...]
    previous: date
    next: date


def safe_link(link: str | None) -> str | None:
    """The link when it is http(s); item links come from outside, so `javascript:` never renders."""
    if not link:
        return None
    try:
        parts = urlsplit(link)
    except ValueError:
        return None
    return link if parts.scheme.lower() in _LINK_SCHEMES and parts.netloc else None


def day_label(day: date) -> str:
    """Short date such as "Sat 7 Nov"."""
    return f"{day:%a} {day.day} {day:%b}"


def anchor(event: Event, tz: tzinfo) -> datetime | None:
    """When the event happens (start, else due), in tz; None when it has neither."""
    moment = event.start if event.start is not None else event.due
    return None if moment is None else moment.astimezone(tz)


def to_row(  # noqa: PLR0913  (each keyword is one independent thing a page may add)
    event: Event,
    tz: tzinfo,
    day: date | None = None,
    *,
    dated: bool = False,
    ctx: str = "",
    now: datetime | None = None,
    marks: Mapping[str, ItemMark] | None = None,
) -> Row:
    """A row for event.

    On `day`, an item that began earlier reads "Ongoing" instead of a time. With `dated` the
    label carries the date too, for lists that span days. With `now` the row says why the item
    has its priority; with `marks` (even an empty mapping) and a `ctx` it carries item controls.
    """
    moment = anchor(event, tz)
    if moment is None:
        when = ""
    elif dated:
        when = f"{day_label(moment.date())}, {moment:%H:%M}"
    elif day is not None and moment.date() < day:
        when = "Ongoing"
    else:
        when = f"{moment:%H:%M}"
        if event.start is None:
            when = f"Due {when}"
    controls = None
    if marks is not None and ctx:
        controls = item_controls(event, marks.get(event.id), tz, ctx=ctx, day=day, dated=dated)
    return Row(
        title=event.title,
        when=when,
        kind=event.kind,
        urgency=event.urgency,
        urgent=event.urgency >= ATTENTION_URGENCY,
        status=event.status,
        link=safe_link(event.link),
        priority=event.priority,
        reason="" if now is None else explain(event, now),
        item=controls,
    )


def today_view(  # noqa: PLR0913
    events: Sequence[Event],
    attention: Sequence[Event],
    day: date,
    tz: tzinfo,
    *,
    now: datetime | None = None,
    marks: Mapping[str, ItemMark] | None = None,
) -> TodayView:
    """Agenda (time order is the service's), weather strip and attention list for day."""
    agenda = tuple(
        to_row(e, tz, day, ctx="agenda", now=now, marks=marks)
        for e in events
        if e.kind != "weather"
    )
    weather = tuple(to_row(e, tz, day, now=now) for e in events if e.kind == "weather")
    flagged = tuple(
        to_row(e, tz, dated=True, ctx="attention", now=now, marks=marks) for e in attention
    )
    one_day = timedelta(days=1)
    return TodayView(day, day_label(day), agenda, weather, flagged, day - one_day, day + one_day)


def week_view(  # noqa: PLR0913
    events: Sequence[Event],
    day: date,
    today: date,
    tz: tzinfo,
    *,
    now: datetime | None = None,
    marks: Mapping[str, ItemMark] | None = None,
) -> WeekView:
    """Seven Monday-based columns; items sit on their start (else due) day, clamped to the week."""
    monday = day - timedelta(days=day.weekday())
    days = [monday + timedelta(days=i) for i in range(7)]
    by_day = _group_by_day(events, tz, first=days[0], last=days[-1])
    columns = tuple(
        DayColumn(
            day=d,
            label=day_label(d),
            is_today=d == today,
            load=sum(e.urgency for e in by_day.get(d, ())),
            rows=tuple(
                to_row(e, tz, d, ctx="week", now=now, marks=marks) for e in by_day.get(d, ())
            ),
        )
        for d in days
    )
    title = f"Week of {day_label(monday)}"
    return WeekView(title, columns, monday - timedelta(days=7), monday + timedelta(days=7))


def month_view(  # noqa: PLR0913
    events: Sequence[Event],
    day: date,
    today: date,
    tz: tzinfo,
    *,
    now: datetime | None = None,
    marks: Mapping[str, ItemMark] | None = None,
) -> MonthView:
    """A Monday-based grid of the month; heat is each day's load against the busiest day."""
    first = day.replace(day=1)
    last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    by_day = _group_by_day(events, tz, first=first, last=last)
    loads = {d: sum(e.urgency for e in items) for d, items in by_day.items()}
    busiest = max(loads.values(), default=0)
    start = first - timedelta(days=first.weekday())
    end = last + timedelta(days=6 - last.weekday())
    cells = [
        MonthCell(
            day=d,
            in_month=first <= d <= last,
            is_today=d == today,
            load=loads.get(d, 0) if first <= d <= last else 0,
            count=len(by_day.get(d, ())) if first <= d <= last else 0,
            level=heat_level(loads.get(d, 0), busiest) if first <= d <= last else 0,
        )
        for d in (start + timedelta(days=i) for i in range((end - start).days + 1))
    ]
    weeks = tuple(tuple(cells[i : i + 7]) for i in range(0, len(cells), 7))
    return MonthView(
        title=f"{calendar.month_name[day.month]} {day.year}",
        weeks=weeks,
        deadlines=tuple(
            to_row(e, tz, dated=True, ctx="deadline", now=now, marks=marks)
            for e in top_deadlines(events)
        ),
        previous=first - timedelta(days=1),
        next=last + timedelta(days=1),
    )


def heat_level(load: int, busiest: int) -> int:
    """0 for an empty day, else 1 to HEAT_LEVELS in proportion to the busiest day."""
    if load <= 0 or busiest <= 0:
        return 0
    return -(-load * HEAT_LEVELS // busiest)


def top_deadlines(events: Iterable[Event]) -> list[Event]:
    """Open deadlines (anything with a due date), most urgent first, at most TOP_DEADLINES."""
    open_deadlines = [e for e in events if e.due is not None and e.status != _DONE]
    open_deadlines.sort(key=lambda e: (-e.urgency, e.due.timestamp() if e.due else 0.0, e.id))
    return open_deadlines[:TOP_DEADLINES]


def _group_by_day(
    events: Iterable[Event], tz: tzinfo, *, first: date, last: date
) -> dict[date, list[Event]]:
    grouped: dict[date, list[Event]] = {}
    for event in events:
        moment = anchor(event, tz)
        if event.kind == "weather" or moment is None:
            continue
        # An item that began before the window overlaps it; show it on the window's first day.
        grouped.setdefault(min(max(moment.date(), first), last), []).append(event)
    return grouped
