"""What the user does to items: check off, notes, their own tasks, and the day's history.

Every item is addressed by its event id. Check-off and notes work on any stored item, synced or
local; creating, changing and deleting work on local tasks only (decision 0120). Store calls run
through `asyncio.to_thread`, like every service.
"""

import asyncio
from datetime import date, datetime

from command_center.core.ledger import (
    HistoryDay,
    ItemMark,
    NoteInput,
    TaskInput,
    TaskPatch,
    apply_task_patch,
    group_history_range,
    is_local,
    local_task_event,
)
from command_center.core.ports import Clock, IdSource, ItemLedger
from command_center.core.schema import Event
from command_center.core.snooze import SnoozePreset, snooze_until
from command_center.core.windows import TimeWindow, day_window
from command_center.services.agenda import AgendaService


class ItemNotFoundError(Exception):
    """No stored item has this id. The message names the id, which is not a secret."""

    def __init__(self, item_id: str) -> None:
        super().__init__(f"No item with id {item_id}")
        self.item_id = item_id


class NotLocalItemError(Exception):
    """The item comes from a source, so only the source can change or delete it."""

    def __init__(self, item_id: str) -> None:
        super().__init__(f"Item {item_id} comes from a source; only local tasks can be changed")
        self.item_id = item_id


class RestoreTooOldError(Exception):
    """A done or dismissed entry from an earlier local day cannot be restored (decision 0334)."""

    def __init__(self, item_id: str) -> None:
        super().__init__(f"Item {item_id} was done or dismissed on an earlier day")
        self.item_id = item_id


class ItemService:
    """Check-off, notes, local tasks and history over an `ItemLedger`."""

    def __init__(
        self, ledger: ItemLedger, agenda: AgendaService, clock: Clock, ids: IdSource
    ) -> None:
        self._ledger = ledger
        self._agenda = agenda
        self._clock = clock
        self._ids = ids

    async def get(self, item_id: str) -> Event:
        """The item as the lists show it (scored now, marked); ItemNotFoundError if unknown."""
        event = await self._agenda.item(item_id)
        if event is None:
            raise ItemNotFoundError(item_id)
        return event

    async def check_off(self, item_id: str) -> Event:
        """Mark the item done by the user; repeating it keeps the first time."""
        await self.get(item_id)
        await asyncio.to_thread(self._ledger.check_off, item_id, self._clock.now())
        return await self.get(item_id)

    async def undo(self, item_id: str) -> Event:
        """Undo the user's check-off; an item the source finished stays done."""
        await self.get(item_id)
        await asyncio.to_thread(self._ledger.undo, item_id)
        return await self.get(item_id)

    async def dismiss(self, item_id: str) -> Event:
        """Dismiss the item: it leaves the lists and shows in History; repeating keeps the time."""
        await self.get(item_id)
        await asyncio.to_thread(self._ledger.dismiss, item_id, self._clock.now())
        return await self.get(item_id)

    async def snooze(self, item_id: str, preset: SnoozePreset) -> Event:
        """Hide the item until the preset's instant in the local day; it then returns by itself."""
        await self.get(item_id)
        until = snooze_until(preset, self._clock.now(), self._agenda.tz)
        await asyncio.to_thread(self._ledger.snooze, item_id, until)
        return await self.get(item_id)

    async def restore(self, item_id: str) -> Event:
        """Undo a dismissal, a snooze and the user's check-off; a source-done item stays done.

        A check-off or dismissal is restorable only on the local day it happened (RestoreTooOldError
        otherwise, decision 0404); clearing a snooze is allowed at any time.
        """
        await self.get(item_id)
        mark = (await asyncio.to_thread(self._ledger.marks, [item_id])).get(item_id)
        if mark is not None:
            acted = mark.dismissed_at or (mark.done_at if mark.done_by == "user" else None)
            if acted is not None and not self._is_today(acted):
                raise RestoreTooOldError(item_id)
        await asyncio.to_thread(self._ledger.restore, item_id)
        return await self.get(item_id)

    async def set_note(self, item_id: str, text: str) -> Event:
        """Attach or replace the item's note; a blank or over-long text is a ValidationError."""
        note = NoteInput(text=text)
        await self.get(item_id)
        await asyncio.to_thread(self._ledger.set_note, item_id, note.text, self._clock.now())
        return await self.get(item_id)

    async def clear_note(self, item_id: str) -> Event:
        """Delete the item's note; none attached is not an error."""
        await self.get(item_id)
        await asyncio.to_thread(self._ledger.clear_note, item_id)
        return await self.get(item_id)

    async def notes(self, item_ids: list[str]) -> dict[str, str]:
        """The note text of each given item that has one."""
        marks = await asyncio.to_thread(self._ledger.marks, item_ids)
        return {item: mark.note for item, mark in marks.items() if mark.note is not None}

    async def marks(self, item_ids: list[str]) -> dict[str, ItemMark]:
        """The note text and check-off of each given item that has either."""
        if not item_ids:
            return {}
        return await asyncio.to_thread(self._ledger.marks, item_ids)

    async def create_task(self, task: TaskInput) -> Event:
        """Store a new local task and return it as the lists show it."""
        event = local_task_event(task, self._ids, self._clock.now())
        await asyncio.to_thread(self._ledger.save_local, event)
        return await self.get(event.id)

    async def update_task(self, item_id: str, patch: TaskPatch) -> Event:
        """Change the given fields of a local task."""
        stored = await self._local(item_id)
        changed = apply_task_patch(stored, patch, self._clock.now())
        if not await asyncio.to_thread(self._ledger.update_local, changed):
            raise ItemNotFoundError(item_id)  # deleted since the read; never bring it back
        return await self.get(item_id)

    async def delete_task(self, item_id: str) -> None:
        """Delete a local task with its note and check-off."""
        await self._local(item_id)
        await asyncio.to_thread(self._ledger.remove_local, item_id)

    async def history(self, first: date, last: date) -> list[HistoryDay]:
        """What was completed (by you or at the source) and what left its source, by day.

        `first` and `last` are calendar days in the configured timezone, both included; only days
        with something to show are returned, oldest first.
        """
        tz = self._agenda.tz
        window = TimeWindow(start=day_window(first, tz).start, end=day_window(last, tz).end)
        entries = await asyncio.to_thread(self._ledger.history, window)
        return group_history_range(entries, tz)

    def _is_today(self, instant: datetime) -> bool:
        tz = self._agenda.tz
        return instant.astimezone(tz).date() == self._clock.now().astimezone(tz).date()

    async def _local(self, item_id: str) -> Event:
        stored = await asyncio.to_thread(self._ledger.find, item_id)
        if stored is None:
            raise ItemNotFoundError(item_id)
        if not is_local(stored):
            raise NotLocalItemError(item_id)
        return stored
