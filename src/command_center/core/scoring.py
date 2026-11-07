"""Deterministic urgency scoring (0-100). The table lives in docs/contracts/core.md."""

from datetime import UTC, datetime, timedelta

from command_center.core.schema import Event

_DONE = "done"
_EMAIL_SCORES = {"overdue": 75, "owed": 50}
_EMAIL_DEFAULT = 5
_ASSIGNMENT_BANDS = (
    (timedelta(hours=24), 90),
    (timedelta(hours=72), 70),
    (timedelta(days=7), 40),
)
_ASSIGNMENT_DEFAULT = 10
_EVENT_SOON = timedelta(hours=2)
_EVENT_LONG_SPAN = timedelta(hours=24)
_EVENT_ENDED = 0
_EVENT_ACTIVE = 60
_EVENT_LONG_SPAN_SCORE = 40
_EVENT_LATER_TODAY = 40
_EVENT_DEFAULT = 10


def urgency(event: Event, now: datetime) -> int:
    """Score event at now; the calendar day for "today" is taken in now's timezone.

    A naive now is a ValueError: astimezone would silently read the host's timezone.
    """
    if now.utcoffset() is None:
        msg = "urgency needs a timezone-aware now"
        raise ValueError(msg)
    if event.kind == "assignment":
        return _assignment(event, now)
    if event.kind == "event":
        return _event(event, now)
    if event.kind == "email":
        return _EMAIL_SCORES.get(event.status or "", _EMAIL_DEFAULT)
    return 0


def _assignment(event: Event, now: datetime) -> int:
    if event.status == _DONE:
        return 0
    if event.due is None:
        return _ASSIGNMENT_DEFAULT
    # UTC subtraction: datetimes sharing one tzinfo would otherwise subtract by wall clock.
    remaining = event.due.astimezone(UTC) - now.astimezone(UTC)
    if remaining < timedelta(0):
        return 100
    for limit, score in _ASSIGNMENT_BANDS:
        if remaining <= limit:
            return score
    return _ASSIGNMENT_DEFAULT


def _event(event: Event, now: datetime) -> int:
    now_utc = now.astimezone(UTC)
    start = None if event.start is None else event.start.astimezone(UTC)
    end = None if event.end is None else event.end.astimezone(UTC)
    if end is not None and end < now_utc:
        return _EVENT_ENDED
    if start is None:
        return _EVENT_DEFAULT
    if end is None and start < now_utc:
        return _EVENT_ENDED
    # Here the event is ongoing (end >= now) or has not started (start >= now when no end).
    if start - now_utc <= _EVENT_SOON:
        long_span = end is not None and end - start >= _EVENT_LONG_SPAN
        return _EVENT_LONG_SPAN_SCORE if long_span else _EVENT_ACTIVE
    if start.astimezone(now.tzinfo).date() == now.date():
        return _EVENT_LATER_TODAY
    return _EVENT_DEFAULT
