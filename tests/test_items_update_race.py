"""Changing a task that a delete removed first is "not found", never a resurrection (decision 0231).

The delete is made to commit between the service's read of the task and its write, by wrapping
the ledger's `find`. SQLite only; on Postgres the same interleaving needs two connections.
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from builders import NOW, make_event
from command_center.core.ledger import TaskInput, TaskPatch
from command_center.core.schema import Event
from command_center.services.items import ItemNotFoundError
from ledger_support import LedgerRig, open_ledger_rig
from sink_support import open_engine


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


def delete_after_the_read(rig: LedgerRig, monkeypatch: pytest.MonkeyPatch, item_id: str) -> None:
    real = rig.ledger.find
    seen: list[str] = []

    def racing(found_id: str, *, user_id: str = "local") -> Event | None:
        stored = real(found_id, user_id=user_id)
        if not seen:
            seen.append(found_id)
            assert rig.ledger.remove_local(item_id) is True  # the delete commits first
        return stored

    monkeypatch.setattr(rig.ledger, "find", racing)


async def test_a_task_deleted_between_the_read_and_the_write_is_not_found_and_stays_deleted(
    rig: LedgerRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = await rig.items.create_task(TaskInput(title="Essay", due=NOW + timedelta(days=2)))
    await rig.items.set_note(task.id, "fake-private-note")
    await rig.items.check_off(task.id)
    delete_after_the_read(rig, monkeypatch, task.id)

    with pytest.raises(ItemNotFoundError):
        await rig.items.update_task(task.id, TaskPatch(title="Renamed"))

    assert rig.ledger.find(task.id) is None
    assert rig.ledger.marks([task.id]) == {}


async def test_an_update_with_no_delete_still_changes_only_the_given_fields(
    rig: LedgerRig,
) -> None:
    task = await rig.items.create_task(
        TaskInput(title="Essay", due=NOW + timedelta(days=2), label="Bio")
    )
    await rig.items.set_note(task.id, "fake-private-note")

    changed = await rig.items.update_task(task.id, TaskPatch(title="Renamed"))

    assert (changed.title, changed.raw.get("label"), changed.due) == (
        "Renamed",
        "Bio",
        NOW + timedelta(days=2),
    )
    assert rig.ledger.marks([task.id])[task.id].note == "fake-private-note"


async def test_the_update_path_never_creates_a_task(rig: LedgerRig) -> None:
    task = await rig.items.create_task(TaskInput(title="Essay", due=NOW + timedelta(days=2)))
    assert rig.ledger.remove_local(task.id) is True

    assert rig.ledger.update_local(task) is False
    assert rig.ledger.find(task.id) is None


async def test_the_update_path_refuses_an_event_that_is_not_a_local_task(rig: LedgerRig) -> None:
    with pytest.raises(ValueError, match="not a local task"):
        rig.ledger.update_local(make_event(id="a", source="canvas", kind="assignment"))
