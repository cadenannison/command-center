"""Reads events back out, scored against the current time and ordered by when they happen."""

import asyncio
from datetime import UTC, date, datetime, tzinfo

from command_center.core.ledger import overlay_marks
from command_center.core.ports import Clock, EventStore, ItemLedger
from command_center.core.schema import Event
from command_center.core.scoring import urgency
from command_center.core.windows import TimeWindow, day_window, month_window, week_window
from command_center.services.horizon import horizon_window

ATTENTION_URGENCY = 70
_ATTENTION_EMAIL_STATUSES = frozenset({"owed", "overdue"})


class AgendaService:
    """Day, week, month and attention views over the event store.

    With a `ledger` every event also carries what the user did to it: `has_note`, and status
    `done` once it is checked off, which the scoring then reads as nothing left to do (0120).
    """

    def __init__(
        self, events: EventStore, clock: Clock, tz: tzinfo, ledger: ItemLedger | None = None
    ) -> None:
        self._events = events
        self._clock = clock
        self._tz = tz
        self._ledger = ledger

    @property
    def tz(self) -> tzinfo:
        """The configured timezone, for views that group events by local day."""
        return self._tz

    def today(self) -> date:
        """The calendar day it is now, in the configured timezone."""
        return self._now().date()

    def now(self) -> datetime:
        """The current time in the configured timezone, for views that explain a score."""
        return self._now()

    async def item(self, item_id: str) -> Event | None:
        """One stored item, marked and scored like the lists; None when it is not stored."""
        if self._ledger is None:
            return None
        stored = await asyncio.to_thread(self._ledger.find, item_id)
        if stored is None:
            return None
        (marked,) = await self._marked([stored])
        return marked.model_copy(update={"urgency": urgency(marked, self._now())})

    async def between(self, window: TimeWindow) -> list[Event]:
        """Events in window, scored now, ordered by start (else due)."""
        return await self._scored(window)

    async def day(self, day: date) -> list[Event]:
        """Events on the calendar day, in the configured timezone."""
        return await self._scored(day_window(day, self._tz))

    async def week(self, day: date) -> list[Event]:
        """Events in the Monday-to-Monday week containing day."""
        return await self._scored(week_window(day, self._tz))

    async def month(self, day: date) -> list[Event]:
        """Events in the calendar month containing day."""
        return await self._scored(month_window(day, self._tz))

    async def attention(self) -> list[Event]:
        """Events needing action, most urgent first, within the sync horizon around today.

        An event qualifies at urgency 70 or more, or when it is an email that is owed or overdue.
        """
        now = self._now()
        scored = await self._scored(horizon_window(now))
        needing = [event for event in scored if _needs_attention(event)]
        return sorted(needing, key=lambda e: (-e.urgency, _anchor(e), e.id))

    def _now(self) -> datetime:
        return self._clock.now().astimezone(self._tz)

    async def _scored(self, window: TimeWindow) -> list[Event]:
        stored = await asyncio.to_thread(self._events.query, window)
        marked = await self._marked(stored)
        now = self._now()
        scored = [event.model_copy(update={"urgency": urgency(event, now)}) for event in marked]
        return sorted(scored, key=lambda e: (_anchor(e), e.id))

    async def _marked(self, events: list[Event]) -> list[Event]:
        if self._ledger is None or not events:
            return events
        marks = await asyncio.to_thread(self._ledger.marks, [event.id for event in events])
        return [overlay_marks(event, marks.get(event.id)) for event in events]


def _needs_attention(event: Event) -> bool:
    if event.urgency >= ATTENTION_URGENCY:
        return True
    return event.kind == "email" and event.status in _ATTENTION_EMAIL_STATUSES


def _anchor(event: Event) -> datetime:
    anchor = event.start if event.start is not None else event.due
    # The store only returns dated events; the fallback keeps an undated one sorted last.
    return datetime.max.replace(tzinfo=UTC) if anchor is None else anchor.astimezone(UTC)
