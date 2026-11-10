"""The item ledger through SyncService (single process): completions, removals, notes, disconnect.

Real SQL stores in one database, SQLite always and Postgres with CC_TEST_POSTGRES_URL. The ledger
is written in the same transaction as the events (decisions 0120, 0121, 0122).
"""

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from builders import NOW, make_event
from command_center.core.errors import FatalError
from command_center.core.ledger import (
    LOCAL_SOURCE,
    LedgerEntry,
    TaskInput,
    local_task_event,
    overlay_marks,
)
from command_center.core.windows import TimeWindow
from command_center.services.queued_sync import QueuedSyncService
from command_center.services.scheduler import SyncEnqueuer
from command_center.services.sync import SyncService
from fake_adapter import FakeAdapter, FetchStep
from fakes import InMemorySecretStore
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import DATABASES, open_engine
from worker_support import SequentialIds

EVERYTHING = TimeWindow(start=NOW - timedelta(days=400), end=NOW + timedelta(days=400))
DONE = "done"


@pytest.fixture(params=DATABASES)
def rig(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine(request.param, tmp_path):
        yield open_ledger_rig(engine)


def make_service(
    rig: LedgerRig, *steps: FetchStep, gate: asyncio.Event | None = None
) -> tuple[SyncService, FakeAdapter]:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-12345678")
    adapter = FakeAdapter("canvas", script=list(steps), gate=gate)
    service = SyncService({"canvas": adapter}, secrets, rig.events, rig.clock, ledger=rig.ledger)
    return service, adapter


def sync_service(rig: LedgerRig, *steps: FetchStep) -> SyncService:
    return make_service(rig, *steps)[0]


def history(rig: LedgerRig) -> list[LedgerEntry]:
    return rig.ledger.history(EVERYTHING)


def stored_ids(rig: LedgerRig) -> list[str]:
    return [event.id for event in rig.events.query(EVERYTHING)]


async def test_an_item_the_source_reports_done_is_completed_at_the_first_sync_that_saw_it(
    rig: LedgerRig,
) -> None:
    service = sync_service(rig, [assignment("a")], [assignment("a", status=DONE)])
    await service.sync("canvas")
    rig.clock.advance(timedelta(hours=1))
    await service.sync("canvas")

    (entry,) = history(rig)
    assert (entry.item_id, entry.group, entry.completed_by) == ("a", "done_by_source", "source")
    assert entry.at == NOW + timedelta(hours=1)


async def test_later_syncs_of_a_done_item_keep_the_first_completion_time(rig: LedgerRig) -> None:
    done = [assignment("a", status=DONE)]
    service = sync_service(rig, [assignment("a")], done, done)
    await service.sync("canvas")
    rig.clock.advance(timedelta(hours=1))
    await service.sync("canvas")
    rig.clock.advance(timedelta(hours=5))
    await service.sync("canvas")

    (entry,) = history(rig)
    assert entry.at == NOW + timedelta(hours=1)


async def test_an_item_that_arrives_already_done_is_completed_at_that_sync(rig: LedgerRig) -> None:
    await sync_service(rig, [assignment("a", status=DONE)]).sync("canvas")

    (entry,) = history(rig)
    assert (entry.item_id, entry.group, entry.at) == ("a", "done_by_source", NOW)


async def test_an_item_that_vanishes_from_the_source_is_removed_not_done(rig: LedgerRig) -> None:
    service = sync_service(rig, [assignment("a"), assignment("b")], [assignment("a")])
    await service.sync("canvas")
    rig.clock.advance(timedelta(hours=2))
    await service.sync("canvas")

    (entry,) = history(rig)
    assert (entry.item_id, entry.group, entry.completed_by) == ("b", "gone", None)
    assert entry.at == NOW + timedelta(hours=2)
    assert entry.title == "Item b"
    assert stored_ids(rig) == ["a"]


async def test_a_done_item_that_then_leaves_the_source_is_not_also_removed(rig: LedgerRig) -> None:
    service = sync_service(rig, [assignment("a", status=DONE)], [])
    await service.sync("canvas")
    await service.sync("canvas")

    assert [(e.item_id, e.group) for e in history(rig)] == [("a", "done_by_source")]


async def test_an_item_stored_done_before_the_ledger_existed_that_leaves_is_not_removed(
    rig: LedgerRig,
) -> None:
    rig.events.upsert([assignment("old", status=DONE)])  # a row the ledger never saw

    await sync_service(rig, []).sync("canvas")

    assert history(rig) == []


async def test_an_item_you_checked_off_that_leaves_the_source_stays_done_by_you(
    rig: LedgerRig,
) -> None:
    service = sync_service(rig, [assignment("a")], [])
    await service.sync("canvas")
    await rig.items.check_off("a")
    await service.sync("canvas")

    assert [(e.item_id, e.group, e.completed_by) for e in history(rig)] == [
        ("a", "done_by_you", "user")
    ]


async def test_a_removed_item_that_comes_back_is_no_longer_removed(rig: LedgerRig) -> None:
    service = sync_service(rig, [assignment("a")], [], [assignment("a")])
    for _ in range(3):
        await service.sync("canvas")

    assert history(rig) == []


async def test_a_failed_fetch_marks_nothing_removed(rig: LedgerRig) -> None:
    service = sync_service(rig, [assignment("a")], FatalError("source down"))
    await service.sync("canvas")
    await service.sync("canvas")

    assert history(rig) == []
    assert stored_ids(rig) == ["a"]


async def test_a_forecast_replaced_every_day_is_not_removed(rig: LedgerRig) -> None:
    today = make_event(id="w1", source="canvas", kind="weather", title="Sunny", start=NOW)
    service = sync_service(rig, [today], [])
    await service.sync("canvas")
    await service.sync("canvas")

    assert history(rig) == []


async def test_an_item_outside_the_sync_window_is_not_removed(rig: LedgerRig) -> None:
    far = assignment("far", hours=24 * 100)  # beyond the 60-day horizon, like test_sync_replace
    rig.events.upsert([far])

    await sync_service(rig, []).sync("canvas")

    assert history(rig) == []
    assert stored_ids(rig) == ["far"]


async def test_a_note_survives_a_resync_and_the_item_leaving_the_window(rig: LedgerRig) -> None:
    service = sync_service(
        rig,
        [assignment("a", title="first")],
        [assignment("a", title="renamed")],
        [],
    )
    await service.sync("canvas")
    await rig.items.set_note("a", "bring the lab report")

    await service.sync("canvas")
    assert rig.ledger.marks(["a"])["a"].note == "bring the lab report"

    await service.sync("canvas")  # a is gone from the source now
    assert stored_ids(rig) == []
    assert rig.ledger.marks(["a"])["a"].note == "bring the lab report"
    (entry,) = history(rig)
    assert (entry.group, entry.note, entry.title) == ("gone", "bring the lab report", "renamed")


async def test_a_user_check_off_survives_a_resync(rig: LedgerRig) -> None:
    service = sync_service(rig, [assignment("a")], [assignment("a")])
    await service.sync("canvas")
    await rig.items.check_off("a")
    await service.sync("canvas")

    assert rig.ledger.marks(["a"])["a"].done_by == "user"


async def test_disconnecting_a_source_deletes_its_ledger_rows_and_notes_and_only_those(
    rig: LedgerRig,
) -> None:
    service = sync_service(
        rig, [assignment("a"), assignment("b"), assignment("c")], [assignment("a"), assignment("b")]
    )
    await service.sync("canvas")
    await service.sync("canvas")  # c is removed: a ledger row with no event behind it
    await rig.items.set_note("a", "note on a")
    await rig.items.check_off("b")
    rig.events.upsert([assignment("g", source="gmail")])
    await rig.items.set_note("g", "note on a gmail item")
    task = await rig.items.create_task(TaskInput(title="Mine", due=NOW + timedelta(days=1)))
    await rig.items.set_note(task.id, "note on my task")

    await service.purge("canvas")

    assert rig.ledger.marks(["a", "b", "c"]) == {}
    assert {e.item_id for e in history(rig)} == set()
    assert set(rig.ledger.marks(["g", task.id])) == {"g", task.id}  # other sources and tasks stay
    assert set(stored_ids(rig)) == {"g", task.id}


async def test_a_sync_that_finishes_after_a_disconnect_leaves_no_ledger_rows(
    rig: LedgerRig,
) -> None:
    gate = asyncio.Event()
    service, adapter = make_service(rig, [assignment("a", status=DONE)], gate=gate)
    running = asyncio.create_task(service.sync("canvas"))
    while adapter.in_flight == 0:  # noqa: ASYNC110  (the fake exposes a counter, no event)
        await asyncio.sleep(0)

    await service.purge("canvas")  # the disconnect lands while the fetch is in flight
    gate.set()
    await running

    assert history(rig) == []
    assert rig.ledger.marks(["a"]) == {}
    assert stored_ids(rig) == []


async def test_a_distributed_disconnect_deletes_the_ledger_rows_too(rig: LedgerRig) -> None:
    rig.events.upsert([assignment("a")])
    await rig.items.set_note("a", "note")
    await rig.items.check_off("a")
    local = local_task_event(
        TaskInput(title="Mine", due=NOW + timedelta(days=1)), SequentialIds(), NOW
    )
    rig.ledger.save_local(local)
    queued = QueuedSyncService(
        ["canvas"],
        cast("SyncEnqueuer", object()),  # purge never queues anything
        rig.states,
        rig.events,
        rig.generations,
        rig.clock,
        ledger=rig.ledger,
    )

    await queued.purge("canvas")

    assert rig.ledger.marks(["a"]) == {}
    assert rig.events.query(EVERYTHING) == [rig.ledger.find(local.id)]
    assert rig.generations.current("canvas") == 1


def test_the_local_source_is_never_swept_by_a_disconnect(rig: LedgerRig) -> None:
    task = local_task_event(
        TaskInput(title="Mine", due=NOW + timedelta(days=1)), SequentialIds(), NOW
    )
    rig.ledger.save_local(task)
    rig.ledger.set_note(task.id, "note", NOW)

    assert rig.ledger.delete_source(LOCAL_SOURCE) == 0
    assert rig.ledger.marks([task.id])[task.id].has_note is True


async def test_an_item_the_source_reopens_stays_in_the_history_of_the_day_it_was_completed(
    rig: LedgerRig,
) -> None:
    service = sync_service(rig, [assignment("a", status=DONE)], [assignment("a")])
    await service.sync("canvas")
    assert [e.reopened for e in history(rig)] == [False]

    rig.clock.advance(timedelta(days=2))
    await service.sync("canvas")

    (entry,) = history(rig)
    assert (entry.item_id, entry.group, entry.completed_by) == ("a", "done_by_source", "source")
    assert entry.at == NOW  # the day it was completed, not the day it was reopened
    assert entry.reopened is True


async def test_a_reopened_item_is_open_again_while_its_completion_is_kept(rig: LedgerRig) -> None:
    service = sync_service(rig, [assignment("a", status=DONE)], [assignment("a")])
    await service.sync("canvas")
    await service.sync("canvas")

    (stored,) = rig.events.query(EVERYTHING)
    mark = rig.ledger.marks(["a"])["a"]
    assert (mark.done_by, mark.done_at) == ("source", NOW)
    assert overlay_marks(stored, mark).status != DONE


async def test_a_reopened_item_keeps_its_note(rig: LedgerRig) -> None:
    service = sync_service(rig, [assignment("a", status=DONE)], [assignment("a")])
    await service.sync("canvas")
    await rig.items.set_note("a", "resubmitted")
    await service.sync("canvas")

    (entry,) = history(rig)
    assert (entry.note, entry.reopened) == ("resubmitted", True)


async def test_an_item_completed_again_after_a_reopen_gets_a_second_entry(
    rig: LedgerRig,
) -> None:
    service = sync_service(
        rig, [assignment("a", status=DONE)], [assignment("a")], [assignment("a", status=DONE)]
    )
    await service.sync("canvas")
    await service.sync("canvas")
    rig.clock.advance(timedelta(days=3))
    await service.sync("canvas")

    assert [(e.at, e.reopened) for e in history(rig)] == [
        (NOW, True),
        (NOW + timedelta(days=3), False),
    ]


async def test_a_reopened_item_that_then_leaves_the_source_is_not_also_removed(
    rig: LedgerRig,
) -> None:
    service = sync_service(rig, [assignment("a", status=DONE)], [assignment("a")], [])
    for _ in range(3):
        await service.sync("canvas")

    assert [(e.item_id, e.group, e.reopened) for e in history(rig)] == [
        ("a", "done_by_source", True)
    ]


async def test_an_item_that_stays_done_is_never_tagged_reopened(rig: LedgerRig) -> None:
    done = [assignment("a", status=DONE)]
    service = sync_service(rig, done, done)
    await service.sync("canvas")
    await service.sync("canvas")

    assert [e.reopened for e in history(rig)] == [False]


async def test_a_source_reopening_an_item_does_not_undo_your_check_off(rig: LedgerRig) -> None:
    service = sync_service(rig, [assignment("a")], [assignment("a")])
    await service.sync("canvas")
    await rig.items.check_off("a")

    await service.sync("canvas")

    assert rig.ledger.marks(["a"])["a"].done_by == "user"


async def test_only_the_source_entry_that_a_reopen_followed_is_tagged(rig: LedgerRig) -> None:
    done = [assignment("a", status=DONE)]
    service = sync_service(rig, [assignment("a")], done, [assignment("a")], done)
    await service.sync("canvas")
    await rig.items.check_off("a")
    rig.clock.advance(timedelta(days=1))
    await service.sync("canvas")  # the source completes it too
    rig.clock.advance(timedelta(days=1))
    await service.sync("canvas")  # and reopens it while your check-off stands
    await rig.items.undo("a")  # undo takes away your entry only
    rig.clock.advance(timedelta(days=1))
    await service.sync("canvas")  # the source completes it again

    assert [(e.completed_by, e.reopened) for e in history(rig)] == [
        ("source", True),
        ("source", False),
    ]


async def test_your_check_off_is_never_tagged_reopened(rig: LedgerRig) -> None:
    service = sync_service(
        rig, [assignment("a")], [assignment("a", status=DONE)], [assignment("a")]
    )
    await service.sync("canvas")
    await rig.items.check_off("a")
    rig.clock.advance(timedelta(days=1))
    await service.sync("canvas")  # the source agrees it is done
    rig.clock.advance(timedelta(days=1))
    await service.sync("canvas")  # then reopens it

    assert [(e.group, e.completed_by, e.reopened) for e in history(rig)] == [
        ("done_by_you", "user", False),
        ("done_by_source", "source", True),
    ]
