"""Reads events back out, scored against the current time and ordered by when they happen."""

import asyncio
from datetime import UTC, date, datetime, tzinfo

from command_center.core.ledger import is_hidden, overlay_marks
from command_center.core.needs_me import NeedsMeItem, needs_me
from command_center.core.ports import Clock, EventStore, ItemLedger
from command_center.core.schema import Event, EventKind
from command_center.core.scoring import urgency
from command_center.core.urgency import TaskItem, task_items
from command_center.core.windows import TimeWindow, day_window, month_window, week_window
from command_center.services.horizon import horizon_window

ATTENTION_URGENCY = 70
_ATTENTION_EMAIL_STATUSES = frozenset({"owed", "overdue"})
UNDATED_TASK_CAP = 200
_UNDATED_WIDENINGS = 4
_UNDATED_KINDS: tuple[EventKind, ...] = ("task", "assignment")


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
        (marked,) = await self._marked([stored])  # not filtered: the actions answer with it
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

    async def tasks(self) -> list[TaskItem]:
        """Tasks, assignments and email within the sync horizon, ranked with their reasons."""
        now = self._now()
        return task_items(await self._task_rows(now), now)

    async def needs_me(self) -> list[NeedsMeItem]:
        """What needs the user now across kinds, from the rows `tasks()` reads (0385, 0386)."""
        now = self._now()
        return needs_me(await self._task_rows(now), now)

    async def _task_rows(self, now: datetime) -> list[Event]:
        stored = await asyncio.to_thread(self._events.query, horizon_window(now))
        undated = await self._undated_visible(now)
        # Marks apply after the cap, so a task the user checked off is dropped here (0372).
        open_undated = [e for e in undated if e.status != "done"]
        rows = [*await self._marked(stored), *open_undated]
        return [event for event in rows if not is_hidden(event, now)]

    async def _undated_visible(self, now: datetime) -> list[Event]:
        """Marked undated tasks, newest first, the cap counted after dismissed and snoozed ones.

        Dismissals are permanent, so they must not use up the cap and push open tasks out of the
        lists (decision 0401). The store applies the cap, so ask for as many more as were hidden,
        a few times at most; a store that returns fewer rows than asked has nothing left.
        """
        limit = UNDATED_TASK_CAP
        shown: list[Event] = []
        for _ in range(_UNDATED_WIDENINGS + 1):
            rows = await self._marked(
                await asyncio.to_thread(self._events.undated_open, _UNDATED_KINDS, limit)
            )
            shown = [e for e in rows if not is_hidden(e, now)]
            if len(rows) < limit or len(rows) == len(shown):
                break
            limit += len(rows) - len(shown)
        return shown[:UNDATED_TASK_CAP]

    def _now(self) -> datetime:
        return self._clock.now().astimezone(self._tz)

    async def _scored(self, window: TimeWindow) -> list[Event]:
        stored = await asyncio.to_thread(self._events.query, window)
        now = self._now()
        shown = [e for e in await self._marked(stored) if not is_hidden(e, now)]
        scored = [event.model_copy(update={"urgency": urgency(event, now)}) for event in shown]
        return sorted(scored, key=lambda e: (_anchor(e), e.id))

    async def _marked(self, events: list[Event]) -> list[Event]:
        if self._ledger is None or not events:
            return events
        marks = await asyncio.to_thread(self._ledger.marks, [event.id for event in events])
        now = self._now()
        return [overlay_marks(event, marks.get(event.id), now) for event in events]


def _needs_attention(event: Event) -> bool:
    if event.urgency >= ATTENTION_URGENCY:
        return True
    return event.kind == "email" and event.status in _ATTENTION_EMAIL_STATUSES


def _anchor(event: Event) -> datetime:
    anchor = event.start if event.start is not None else event.due
    # The store only returns dated events; the fallback keeps an undated one sorted last.
    return datetime.max.replace(tzinfo=UTC) if anchor is None else anchor.astimezone(UTC)
