"""Fixes after the A1a review: fresh rows under the lock, the undated cap, one History line.

Decisions 0398 and 0401. SQLite always, Postgres with CC_TEST_POSTGRES_URL. What only real
concurrency can show (two writers waiting on one event-row lock) is not here; see the note on the
stale-row test.
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from builders import NOW, make_event
from command_center.core.windows import TimeWindow
from command_center.services.agenda import UNDATED_TASK_CAP
from command_center.services.sync import SyncService
from command_center.storage.sqlite_items import _known_row  # pyright: ignore[reportPrivateUsage]
from command_center.storage.sqlite_ledger_tables import LedgerRow
from fake_adapter import FakeAdapter, FetchStep
from fakes import InMemorySecretStore
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import DATABASES, open_engine

EVERYTHING = TimeWindow(start=NOW - timedelta(days=30), end=NOW + timedelta(days=30))


@pytest.fixture(params=DATABASES)
def rig(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine(request.param, tmp_path):
        yield open_ledger_rig(engine)


def syncing(rig: LedgerRig, *steps: FetchStep) -> SyncService:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-12345678")
    adapter = FakeAdapter("canvas", script=list(steps))
    return SyncService({"canvas": adapter}, secrets, rig.events, rig.clock, ledger=rig.ledger)


def groups(rig: LedgerRig) -> list[tuple[str, str]]:
    return [(e.item_id, e.group) for e in rig.ledger.history(EVERYTHING)]


# ---- finding 1: the row is read after the lock ----


def test_a_row_cached_in_the_session_is_refreshed_after_the_event_lock(rig: LedgerRig) -> None:
    # A stale copy is what a writer holds when it waited on the lock while another committed. No
    # second writer is needed to show the read: load the row, change it behind the session's
    # back, then ask for it the way a write does. That the lock itself serialises two writers on
    # Postgres is not shown here; only a run with two concurrent connections can show that.
    rig.events.upsert([assignment("a")])
    rig.ledger.snooze("a", NOW + timedelta(days=1))
    with Session(rig.engine) as session:
        cached = session.get(LedgerRow, ("local", "a"))
        assert cached is not None
        assert cached.dismissed_at is None
        with rig.engine.begin() as other:
            other.execute(update(LedgerRow).values(dismissed_at=NOW, snoozed_until=None))

        row = _known_row(session, "a", "local")

        assert row is not None
        assert row.dismissed_at == NOW
        assert row.snoozed_until is None


def test_an_action_after_another_has_committed_acts_on_what_it_left(rig: LedgerRig) -> None:
    rig.events.upsert([assignment("a")])
    rig.ledger.dismiss("a", NOW)
    rig.ledger.dismiss("a", NOW + timedelta(hours=1))
    rig.ledger.snooze("a", NOW + timedelta(days=1))
    assert rig.ledger.marks(["a"])["a"].dismissed_at is None  # snooze ended the dismissal

    rig.ledger.dismiss("a", NOW + timedelta(hours=2))
    mark = rig.ledger.marks(["a"])["a"]

    assert (mark.dismissed_at, mark.snoozed_until) == (NOW + timedelta(hours=2), None)
    rig.ledger.check_off("a", NOW + timedelta(hours=3))
    assert groups(rig) == [("a", "done_by_you")]


# ---- finding 2: the cap counts only items that can show ----


async def test_dismissed_undated_tasks_do_not_use_up_the_cap(rig: LedgerRig) -> None:
    total = UNDATED_TASK_CAP + 15
    rig.events.upsert(
        [
            make_event(
                id=f"t{n:03}",
                source="local",
                kind="task",
                fetched_at=NOW - timedelta(minutes=n),  # t000 is the newest
            )
            for n in range(total)
        ]
    )
    for n in range(15):  # the 15 newest, which the store returns first
        rig.ledger.dismiss(f"t{n:03}", NOW)

    shown = {t.id for t in await rig.agenda.tasks()}

    assert len(shown) == UNDATED_TASK_CAP
    assert f"t{total - 1:03}" in shown  # the oldest was pushed out before the fix
    assert not shown & {f"t{n:03}" for n in range(15)}


async def test_snoozed_undated_tasks_do_not_use_up_the_cap_either(rig: LedgerRig) -> None:
    total = UNDATED_TASK_CAP + 5
    rig.events.upsert(
        [
            make_event(
                id=f"t{n:03}",
                source="local",
                kind="task",
                fetched_at=NOW - timedelta(minutes=n),
            )
            for n in range(total)
        ]
    )
    for n in range(5):
        rig.ledger.snooze(f"t{n:03}", NOW + timedelta(days=1))

    shown = {t.id for t in await rig.agenda.tasks()}

    assert len(shown) == UNDATED_TASK_CAP
    assert f"t{total - 1:03}" in shown


async def test_the_cap_still_holds_when_nothing_is_hidden(rig: LedgerRig) -> None:
    rig.events.upsert(
        [
            make_event(
                id=f"t{n:03}",
                source="local",
                kind="task",
                fetched_at=NOW - timedelta(minutes=n),
            )
            for n in range(UNDATED_TASK_CAP + 5)
        ]
    )

    shown = {t.id for t in await rig.agenda.tasks()}

    assert len(shown) == UNDATED_TASK_CAP
    assert "t204" not in shown


# ---- finding 5: one History line, with the outcome of the latest action ----


async def test_a_source_done_item_the_user_dismissed_appears_once_as_dismissed(
    rig: LedgerRig,
) -> None:
    await syncing(rig, [assignment("a", status="done")]).sync("canvas")
    assert groups(rig) == [("a", "done_by_source")]
    rig.clock.advance(timedelta(hours=1))

    await rig.items.dismiss("a")

    assert groups(rig) == [("a", "dismissed")]


async def test_restoring_that_item_shows_the_source_completion_again(rig: LedgerRig) -> None:
    await syncing(rig, [assignment("a", status="done")]).sync("canvas")
    rig.clock.advance(timedelta(hours=1))
    await rig.items.dismiss("a")

    await rig.items.restore("a")

    assert groups(rig) == [("a", "done_by_source")]


async def test_a_source_completion_after_the_dismissal_is_the_latest_action(
    rig: LedgerRig,
) -> None:
    service = syncing(rig, [assignment("a")], [assignment("a", status="done")])
    await service.sync("canvas")
    await rig.items.dismiss("a")
    rig.clock.advance(timedelta(hours=1))

    await service.sync("canvas")

    assert groups(rig) == [("a", "done_by_source")]
