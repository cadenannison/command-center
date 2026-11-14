"""Check-off, notes, local tasks and the day's history (decisions 0120, 0123, 0125, 0126).

Always mounted; every route answers 404 while the container has no item service. The writes are
for the Mac's own web UI and for curl on loopback: a paired phone may only read, so only
`GET /v1/history` is open to it (`api/policy.py`).
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict

from command_center.api.deps import ContainerDep
from command_center.api.errors import INVALID_REQUEST, NOT_FOUND, ErrorBody
from command_center.core.ledger import HistoryDay, NoteInput, TaskInput, TaskPatch
from command_center.core.schema import Event
from command_center.core.snooze import SnoozePreset
from command_center.services.container import Container
from command_center.services.items import (
    ItemNotFoundError,
    ItemService,
    NotLocalItemError,
    RestoreTooOldError,
)

router = APIRouter(prefix="/v1", tags=["items"])

ITEMS_OFF = "Items are not enabled"
NOT_LOCAL = "Only local tasks can be changed or deleted"
NO_SUCH_ITEM = "No such item"
RESTORE_TOO_OLD = "Only items done or dismissed today can be restored"
MAX_HISTORY_DAYS = 366

_CONFLICT: dict[int | str, dict[str, Any]] = {409: {"model": ErrorBody}}
_BAD_ITEM = {**NOT_FOUND, **INVALID_REQUEST}


def _service(container: Container) -> ItemService:
    if container.items is None:
        raise HTTPException(status_code=404, detail=ITEMS_OFF)
    return container.items


@router.get(
    "/history",
    summary="What was completed or left its source on a day",
    responses=_BAD_ITEM,
)
async def history(
    container: ContainerDep,
    first: Annotated[date, Query(alias="from")],
    last: Annotated[date, Query(alias="to")],
) -> list[HistoryDay]:
    """Items completed (by you, or seen done at the source) and items that disappeared, by day.

    `from` and `to` are calendar days in the configured timezone, both included, at most 366 days
    apart. Only days with something to show are returned, oldest first. Each entry carries
    `completed_by` (`user`, `source`, or null for an item that disappeared), its source, title and
    its note, if it has one. `reopened` is true for an item the source completed and later reported
    open again; it stays on the day it was completed (decision 0130).
    """
    if last < first or (last - first).days >= MAX_HISTORY_DAYS:
        issue = {
            "type": "value_error",
            "loc": ("query", "to"),
            "msg": f"`to` must be on or after `from`, at most {MAX_HISTORY_DAYS} days apart",
            "input": None,
        }
        raise RequestValidationError([issue])
    return await _service(container).history(first, last)


@router.post("/items", status_code=201, summary="Create a local task", responses=_BAD_ITEM)
async def create_item(container: ContainerDep, task: TaskInput) -> Event:
    """Store a task of your own (source `local`, kind `task`). No sync ever prunes it."""
    return await _service(container).create_task(task)


@router.patch(
    "/items/{item_id}",
    summary="Change a local task",
    responses={**_BAD_ITEM, **_CONFLICT},
)
async def update_item(container: ContainerDep, item_id: str, patch: TaskPatch) -> Event:
    """Change the title, due time or label of a local task; 409 for an item from a source."""
    try:
        return await _service(container).update_task(item_id, patch)
    except ItemNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH_ITEM) from None
    except NotLocalItemError:
        raise HTTPException(status_code=409, detail=NOT_LOCAL) from None


@router.delete(
    "/items/{item_id}",
    status_code=204,
    summary="Delete a local task",
    responses={**_BAD_ITEM, **_CONFLICT},
)
async def delete_item(container: ContainerDep, item_id: str) -> Response:
    """Delete a local task with its note and check-off; 409 for an item from a source."""
    try:
        await _service(container).delete_task(item_id)
    except ItemNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH_ITEM) from None
    except NotLocalItemError:
        raise HTTPException(status_code=409, detail=NOT_LOCAL) from None
    return Response(status_code=204)


@router.post("/items/{item_id}/done", summary="Check an item off", responses=_BAD_ITEM)
async def check_off(container: ContainerDep, item_id: str) -> Event:
    """Mark the item done. It then scores 0, has no priority and leaves the attention list."""
    try:
        return await _service(container).check_off(item_id)
    except ItemNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH_ITEM) from None


@router.delete("/items/{item_id}/done", summary="Undo a check-off", responses=_BAD_ITEM)
async def undo_check_off(container: ContainerDep, item_id: str) -> Event:
    """Undo your own check-off; an item the source marks done stays done."""
    try:
        return await _service(container).undo(item_id)
    except ItemNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH_ITEM) from None


class SnoozeRequest(BaseModel):
    """How long to hide an item: a preset, worked out on the server in the local day."""

    model_config = ConfigDict(extra="forbid")

    preset: SnoozePreset


@router.post("/items/{item_id}/dismiss", summary="Dismiss an item", responses=_BAD_ITEM)
async def dismiss(container: ContainerDep, item_id: str) -> Event:
    """Dismiss: the item leaves every list and shows in History. Repeating it changes nothing."""
    try:
        return await _service(container).dismiss(item_id)
    except ItemNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH_ITEM) from None


@router.post("/items/{item_id}/snooze", summary="Snooze an item", responses=_BAD_ITEM)
async def snooze(container: ContainerDep, item_id: str, body: SnoozeRequest) -> Event:
    """Hide the item until `later_today`, `tomorrow_morning` or `next_week` (local day).

    The reply carries `snoozed_until`. Snoozing again replaces the time; the item comes back by
    itself and is not in History.
    """
    try:
        return await _service(container).snooze(item_id, body.preset)
    except ItemNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH_ITEM) from None


@router.post(
    "/items/{item_id}/restore",
    summary="Restore an item",
    responses={**_BAD_ITEM, **_CONFLICT},
)
async def restore(container: ContainerDep, item_id: str) -> Event:
    """Undo done, dismissed or snoozed; an item the source marks done stays done. Idempotent.

    A check-off or dismissal from an earlier local day is 409; clearing a snooze always works.
    """
    try:
        return await _service(container).restore(item_id)
    except ItemNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH_ITEM) from None
    except RestoreTooOldError:
        raise HTTPException(status_code=409, detail=RESTORE_TOO_OLD) from None


@router.put("/items/{item_id}/notes", summary="Set an item's note", responses=_BAD_ITEM)
async def put_note(container: ContainerDep, item_id: str, note: NoteInput) -> Event:
    """Attach or replace the note (1 to 4000 characters). The item then has `has_note` true."""
    try:
        return await _service(container).set_note(item_id, note.text)
    except ItemNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH_ITEM) from None


@router.delete("/items/{item_id}/notes", summary="Delete an item's note", responses=_BAD_ITEM)
async def delete_note(container: ContainerDep, item_id: str) -> Event:
    """Delete the note; an item with none is returned unchanged."""
    try:
        return await _service(container).clear_note(item_id)
    except ItemNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH_ITEM) from None
