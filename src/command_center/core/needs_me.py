"""What needs the user's attention across kinds, for the Needs me widget (decisions 0385, 0386).

Pure: reads only the items and the `now` it is given, through `urgency.assess`. No clock, I/O,
randomness or AI, so the same input always gives the same list.
"""

from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict

from command_center.core.schema import Event, EventKind
from command_center.core.urgency import UrgencyReason, assess

NEEDS_ME_MIN_PRIORITY = 5
NEEDS_ME_LIMIT = 20

_KINDS = ("assignment", "task", "email", "event")
_OVERDUE_CODES = frozenset({"overdue", "reply_overdue"})
_EVENT_CODES = frozenset({"event_now", "event_today"})


class NeedsMeItem(BaseModel):
    """One row of the Needs me list. `at` is the due time, else the start, else None."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: EventKind
    title: str
    source: str
    at: AwareDatetime | None
    link: str | None
    priority: int
    reasons: list[UrgencyReason]


def needs_me(
    items: Iterable[Event], now: datetime, limit: int = NEEDS_ME_LIMIT
) -> list[NeedsMeItem]:
    """The items that need attention now, most urgent first, at most `limit`, each id once.

    An item that is not done qualifies when its priority is at least `NEEDS_ME_MIN_PRIORITY` or it
    is overdue (a task or assignment past due, or an email reply marked overdue). A calendar event
    qualifies only while in progress or when it starts within 24 hours, whatever its priority.
    Items with no time never qualify unless they reach the priority threshold on their own, which
    an undated item cannot. Order: priority descending, then time ascending (none last), then id.
    """
    if limit < 0:
        msg = "limit must not be negative"
        raise ValueError(msg)
    rows: list[NeedsMeItem] = []
    for event in items:
        if event.kind not in _KINDS or event.status == "done":
            continue
        found = assess(event, now)
        codes = {reason.code for reason in found.reasons}
        if not _qualifies(event, found.priority, codes):
            continue
        rows.append(
            NeedsMeItem(
                id=event.id,
                kind=event.kind,
                title=event.title,
                source=event.source,
                at=_at(event),
                link=event.link,
                priority=found.priority,
                reasons=found.reasons,
            )
        )
    rows.sort(key=lambda row: (-row.priority, _time_key(row), row.id))
    seen: set[str] = set()
    unique: list[NeedsMeItem] = []
    for row in rows:
        if row.id not in seen:
            seen.add(row.id)
            unique.append(row)
    return unique[:limit]


def _qualifies(event: Event, priority: int, codes: set[str]) -> bool:
    if _at(event) is None:
        return False
    if event.kind == "event":
        return bool(codes & _EVENT_CODES)
    return priority >= NEEDS_ME_MIN_PRIORITY or bool(codes & _OVERDUE_CODES)


def _at(event: Event) -> datetime | None:
    return event.due if event.due is not None else event.start


def _time_key(row: NeedsMeItem) -> tuple[bool, datetime]:
    if row.at is None:
        return (True, datetime.max.replace(tzinfo=UTC))
    return (False, row.at.astimezone(UTC))
