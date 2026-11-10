"""Deterministic urgency scoring (0-100) and its reason. The table lives in docs/contracts/core.md.

`urgency` and `explain` read one assessment, so a reason can never disagree with its score.
"""

from datetime import UTC, datetime, timedelta

from command_center.core.schema import Event

_DONE = "done"
_EMAIL_SCORES = {"overdue": (75, "Reply overdue"), "owed": (50, "Reply owed")}
_EMAIL_DEFAULT = (5, "No reply owed")
_DUE_ITEM_KINDS = ("assignment", "task")
_OVERDUE = 100
_DUE_BANDS = (
    (timedelta(hours=24), 90),
    (timedelta(hours=72), 70),
    (timedelta(days=7), 40),
)
_DUE_DEFAULT = 10
_EVENT_SOON = timedelta(hours=2)
_EVENT_LONG_SPAN = timedelta(hours=24)
_EVENT_ENDED = 0
_EVENT_ACTIVE = 60
_EVENT_LONG_SPAN_SCORE = 40
_EVENT_LATER_TODAY = 40
_EVENT_DEFAULT = 10
_MINUTE = timedelta(minutes=1)
_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)
_SPAN_IN_HOURS_BELOW = timedelta(hours=48)

type _Assessment = tuple[int, str]


def urgency(event: Event, now: datetime) -> int:
    """Score event at now; the calendar day for "today" is taken in now's timezone.

    A naive now is a ValueError: astimezone would silently read the host's timezone.
    """
    return _assess(event, now)[0]


def explain(event: Event, now: datetime) -> str:
    """Say in a few words why event has its score at now; same rules and ValueError as urgency."""
    return _assess(event, now)[1]


def _assess(event: Event, now: datetime) -> _Assessment:
    if now.utcoffset() is None:
        msg = "urgency needs a timezone-aware now"
        raise ValueError(msg)
    if event.status == _DONE:
        return 0, "Done, no priority"
    if event.kind in _DUE_ITEM_KINDS:
        return _due_item(event, now)
    if event.kind == "event":
        return _event(event, now)
    if event.kind == "email":
        return _EMAIL_SCORES.get(event.status or "", _EMAIL_DEFAULT)
    return 0, "Weather, no priority"


def _due_item(event: Event, now: datetime) -> _Assessment:
    if event.due is None:
        return _DUE_DEFAULT, "No due date"
    state = "not submitted" if event.kind == "assignment" else "not done"
    # UTC subtraction: datetimes sharing one tzinfo would otherwise subtract by wall clock.
    remaining = event.due.astimezone(UTC) - now.astimezone(UTC)
    if remaining < timedelta(0):
        return _OVERDUE, f"Overdue by {_span(-remaining)}, {state}"
    reason = f"Due in {_span(remaining)}, {state}"
    for limit, score in _DUE_BANDS:
        if remaining <= limit:
            return score, reason
    return _DUE_DEFAULT, reason


def _event(event: Event, now: datetime) -> _Assessment:
    now_utc = now.astimezone(UTC)
    start = None if event.start is None else event.start.astimezone(UTC)
    end = None if event.end is None else event.end.astimezone(UTC)
    if end is not None and end < now_utc:
        return _EVENT_ENDED, "Already over"
    if start is None:
        return _EVENT_DEFAULT, "No start time"
    if end is None and start < now_utc:
        return _EVENT_ENDED, "Already over"
    # Here the event is ongoing (end >= now) or has not started (start >= now when no end).
    if start - now_utc <= _EVENT_SOON:
        return _active_event(start, end, now_utc)
    if start.astimezone(now.tzinfo).date() == now.date():
        return _EVENT_LATER_TODAY, "Later today"
    return _EVENT_DEFAULT, "Not today"


def _active_event(start: datetime, end: datetime | None, now_utc: datetime) -> _Assessment:
    long_span = end is not None and end - start >= _EVENT_LONG_SPAN
    phase = "in progress" if start <= now_utc else f"starts in {_span(start - now_utc)}"
    if long_span:
        return _EVENT_LONG_SPAN_SCORE, f"Long event: {phase}"
    return _EVENT_ACTIVE, phase[:1].upper() + phase[1:]


def _span(delta: timedelta) -> str:
    """A non-negative duration as whole minutes (under 1h), hours (under 48h) or days."""
    if delta < _HOUR:
        return _plural(max(1, delta // _MINUTE), "minute")
    if delta < _SPAN_IN_HOURS_BELOW:
        return _plural(delta // _HOUR, "hour")
    return _plural(delta // _DAY, "day")


def _plural(count: int, unit: str) -> str:
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
