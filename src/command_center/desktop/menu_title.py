"""The menu-bar title: the next open deadline, worded for a glance. Pure: no rumps, no clock."""

import math
from collections.abc import Iterable
from datetime import datetime, tzinfo

from command_center.core.schema import Event

IDLE_TITLE = "CC"
OFFLINE_TITLE = "CC offline"
TITLE_LIMIT = 28
_SEPARATOR = " · "
_MINUTE = 60
_HOUR = 3600
_WEEK_DAYS = 7
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def next_deadline(events: Iterable[Event], now: datetime) -> Event | None:
    """The soonest open assignment that is not yet due; ties break by id."""
    due_ones = [
        event
        for event in events
        if event.kind == "assignment"
        and event.due is not None
        and event.due >= now
        and event.status != "done"
    ]
    return min(due_ones, key=lambda e: (e.due or now, e.id), default=None)


def describe_due(due: datetime, now: datetime, tz: tzinfo) -> str:
    """Word a due instant relative to now: 'in 25m', 'today 10:00', 'Tue 05:00', '27 Nov'."""
    seconds = (due - now).total_seconds()
    if seconds < 0:
        return "due now"
    if seconds < _HOUR:
        return f"in {max(1, math.ceil(seconds / _MINUTE))}m"
    local = due.astimezone(tz)
    clock = f"{local:%H:%M}"
    days_ahead = (local.date() - now.astimezone(tz).date()).days
    if days_ahead == 0:
        return f"today {clock}"
    if days_ahead == 1:
        return f"tomorrow {clock}"
    if days_ahead < _WEEK_DAYS:
        return f"{_WEEKDAYS[local.weekday()]} {clock}"
    return f"{local.day} {_MONTHS[local.month - 1]}"


def menu_title(deadline: Event | None, now: datetime, tz: tzinfo) -> str:
    """The title for the next deadline, or the idle title when there is none."""
    if deadline is None or deadline.due is None:
        return IDLE_TITLE
    title = " ".join(deadline.title.split())
    if len(title) > TITLE_LIMIT:
        title = title[: TITLE_LIMIT - 1] + "…"
    return f"{title}{_SEPARATOR}{describe_due(deadline.due, now, tz)}"
