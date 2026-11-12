"""Explainable urgency: a 1-10 priority and reasons whose points add up to it (0332, 0370).

Pure: `assess(event, now)` reads only the item's kind, source, status, due, start and end, and the
`now` it is given. No clock, I/O, randomness or AI, so the same input always gives the same answer.
The older 0-100 `scoring.urgency` stays as it is; this is the score the Tasks list shows.
"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict

from command_center.core.schema import Event

MIN_PRIORITY = 1
MAX_PRIORITY = 10
LOCAL_SOURCE = "local"

# (due within this long, points). Overdue (below zero) outranks every band.
DUE_BANDS: tuple[tuple[timedelta, int], ...] = (
    (timedelta(hours=6), 7),
    (timedelta(hours=24), 6),
    (timedelta(hours=48), 5),  # "soon" is the next 48 hours
    (timedelta(days=7), 3),
    (timedelta(days=14), 1),
)
OVERDUE_POINTS = 8
LONG_OVERDUE = timedelta(days=2)
LONG_OVERDUE_POINTS = 1
MANUAL_TASK_POINTS = 1
EMAIL_POINTS = {"overdue": 5, "owed": 3}
# (waiting at least this long, points); the longest match counts.
EMAIL_AGE_BANDS: tuple[tuple[timedelta, int], ...] = (
    (timedelta(hours=72), 2),
    (timedelta(hours=24), 1),
)
EVENT_NOW_WITHIN = timedelta(hours=2)
EVENT_NOW_POINTS = 4
EVENT_TODAY_WITHIN = timedelta(hours=24)
EVENT_TODAY_POINTS = 2

_DUE_KINDS = ("assignment", "task")
_TASK_KINDS = ("assignment", "task", "email")
_MINUTE = timedelta(minutes=1)
_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)
_HOURS_UNTIL = timedelta(hours=48)


class UrgencyReason(BaseModel):
    """One line of the answer to "Why is this a 9?": a short sentence and the points it adds."""

    model_config = ConfigDict(frozen=True)

    code: str
    points: int
    text: str


class Urgency(BaseModel):
    """`priority` is `score` clamped to 1-10; `score` is the sum of the reasons' points."""

    model_config = ConfigDict(frozen=True)

    priority: int
    score: int
    reasons: list[UrgencyReason]


class TaskItem(BaseModel):
    """One row of the Tasks list: the item, whether it is done, and why it ranks where it does."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    source: str
    due: AwareDatetime | None
    link: str | None
    done: bool
    priority: int
    reasons: list[UrgencyReason]


def task_items(events: Iterable[Event], now: datetime) -> list[TaskItem]:
    """Actionable items (tasks, assignments, email) ranked: priority high to low, then due soonest.

    Calendar events and weather are not tasks. Items with no due time come after dated ones of the
    same priority; the id breaks every remaining tie so the order is stable.
    """
    rows = [(event, assess(event, now)) for event in events if event.kind in _TASK_KINDS]
    rows.sort(key=lambda row: (-row[1].priority, _due_key(row[0]), row[0].id))
    return [
        TaskItem(
            id=event.id,
            title=event.title,
            source=event.source,
            due=event.due,
            link=event.link,
            done=event.status == "done",
            priority=found.priority,
            reasons=found.reasons,
        )
        for event, found in rows
    ]


def _due_key(event: Event) -> tuple[bool, datetime]:
    if event.due is None:
        return (True, datetime.max.replace(tzinfo=UTC))
    return (False, event.due.astimezone(UTC))


def assess(event: Event, now: datetime) -> Urgency:
    """Priority and reasons for event at now. A naive now is a ValueError, never the host zone."""
    if now.utcoffset() is None:
        msg = "assess needs a timezone-aware now"
        raise ValueError(msg)
    now_utc = now.astimezone(UTC)
    reasons = _reasons(event, now_utc)
    if not reasons:
        reasons = [UrgencyReason(code="none", points=0, text="Nothing makes this urgent right now")]
    score = sum(reason.points for reason in reasons)
    return Urgency(
        priority=max(MIN_PRIORITY, min(MAX_PRIORITY, score)), score=score, reasons=reasons
    )


def _reasons(event: Event, now: datetime) -> list[UrgencyReason]:
    if event.status == "done":
        return [UrgencyReason(code="done", points=0, text="Already done, nothing left to do")]
    found: list[UrgencyReason] = []
    if event.kind in _DUE_KINDS and event.due is not None:
        found.extend(_due(event.due.astimezone(UTC) - now))
    if event.kind == "task" and event.source == LOCAL_SOURCE:
        found.append(
            UrgencyReason(
                code="manual", points=MANUAL_TASK_POINTS, text="You added this task yourself"
            )
        )
    if event.kind == "email":
        found.extend(_email(event, now))
    if event.kind == "event":
        found.extend(_event(event, now))
    return found


def _due(remaining: timedelta) -> list[UrgencyReason]:
    if remaining < timedelta(0):
        late = -remaining
        found = [
            UrgencyReason(code="overdue", points=OVERDUE_POINTS, text=f"Overdue by {_span(late)}")
        ]
        if late >= LONG_OVERDUE:
            found.append(
                UrgencyReason(
                    code="overdue_long",
                    points=LONG_OVERDUE_POINTS,
                    text="Overdue for two days or more",
                )
            )
        return found
    for limit, points in DUE_BANDS:
        if remaining <= limit:
            return [UrgencyReason(code="due", points=points, text=f"Due in {_span(remaining)}")]
    return []


def _email(event: Event, now: datetime) -> list[UrgencyReason]:
    points = EMAIL_POINTS.get(event.status or "")
    if points is None:
        return []
    owed = event.status == "owed"
    found = [
        UrgencyReason(
            code="reply_owed" if owed else "reply_overdue",
            points=points,
            text="A reply is owed" if owed else "Your reply is overdue",
        )
    ]
    if event.start is not None:
        waiting = now - event.start.astimezone(UTC)
        for floor, age_points in EMAIL_AGE_BANDS:
            if waiting >= floor:
                found.append(
                    UrgencyReason(
                        code="reply_age",
                        points=age_points,
                        text=f"Waiting {_span(waiting)} for your reply",
                    )
                )
                break
    return found


def _event(event: Event, now: datetime) -> list[UrgencyReason]:
    if event.start is None:
        return []
    start = event.start.astimezone(UTC)
    end = None if event.end is None else event.end.astimezone(UTC)
    until = start - now
    if until < timedelta(0):
        if end is None or end < now:
            return []
        return [UrgencyReason(code="event_now", points=EVENT_NOW_POINTS, text="In progress now")]
    if until <= EVENT_NOW_WITHIN:
        return [
            UrgencyReason(
                code="event_now", points=EVENT_NOW_POINTS, text=f"Starts in {_span(until)}"
            )
        ]
    if until <= EVENT_TODAY_WITHIN:
        return [
            UrgencyReason(
                code="event_today", points=EVENT_TODAY_POINTS, text=f"Starts in {_span(until)}"
            )
        ]
    return []


def _span(delta: timedelta) -> str:
    """A non-negative duration as whole minutes (under 1h), hours (under 48h) or days."""
    if delta < _HOUR:
        return _plural(max(1, delta // _MINUTE), "minute")
    if delta < _HOURS_UNTIL:
        return _plural(delta // _HOUR, "hour")
    return _plural(delta // _DAY, "day")


def _plural(count: int, unit: str) -> str:
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
