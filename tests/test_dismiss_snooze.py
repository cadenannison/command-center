"""Dismiss, snooze and restore through the real SQL ledger (decisions 0334, 0398, 0399).

SQLite always, Postgres with CC_TEST_POSTGRES_URL.
"""

import asyncio
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from builders import NOW, make_event
from command_center.core.ledger import LedgerEntry
from command_center.core.windows import TimeWindow
from command_center.services.agenda import AgendaService
from command_center.services.items import ItemNotFoundError
from command_center.services.summary import SummaryService
from command_center.services.sync import SyncService
from command_center.storage.sqlite_ledger import ensure_ledger_schema
from fake_adapter import FakeAdapter, FetchStep
from fakes import FakeSummaryProvider, InMemorySecretStore, InMemorySummaryStore
from ledger_support import DENVER, LedgerRig, assignment, open_ledger_rig
from sink_support import DATABASES, open_engine
from summary_support import GOOD

EVERYTHING = TimeWindow(start=NOW - timedelta(days=30), end=NOW + timedelta(days=30))
DAY = date(2026, 11, 7)  # NOW is 05:00 on this day in America/Denver


@pytest.fixture(params=DATABASES)
def rig(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine(request.param, tmp_path):
        yield open_ledger_rig(engine)


def seed(rig: LedgerRig, *ids: str) -> None:
    rig.events.upsert([assignment(item, hours=1) for item in ids])


def history(rig: LedgerRig) -> list[LedgerEntry]:
    return rig.ledger.history(EVERYTHING)


async def task_ids(rig: LedgerRig) -> list[str]:
    return [t.id for t in await rig.agenda.tasks()]


def syncing(rig: LedgerRig, *steps: FetchStep) -> SyncService:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-12345678")
    adapter = FakeAdapter("canvas", script=list(steps))
    return SyncService({"canvas": adapter}, secrets, rig.events, rig.clock, ledger=rig.ledger)


# ---- dismiss ----


async def test_dismissing_marks_the_item_with_a_timestamp(rig: LedgerRig) -> None:
    seed(rig, "a")

    event = await rig.items.dismiss("a")

    assert event.dismissed_at == NOW
    assert event.snoozed_until is None


async def test_dismissing_twice_keeps_the_first_time(rig: LedgerRig) -> None:
    seed(rig, "a")
    await rig.items.dismiss("a")
    rig.clock.advance(timedelta(hours=2))

    event = await rig.items.dismiss("a")

    assert event.dismissed_at == NOW
    assert [e.at for e in history(rig)] == [NOW]


async def test_dismissing_an_unknown_item_is_not_found(rig: LedgerRig) -> None:
    with pytest.raises(ItemNotFoundError):
        await rig.items.dismiss("nope")


async def test_a_dismissed_item_is_in_history_as_dismissed_next_to_done_ones(
    rig: LedgerRig,
) -> None:
    seed(rig, "a", "b")
    await rig.items.dismiss("a")
    await rig.items.check_off("b")

    (day,) = await rig.items.history(DAY, DAY)

    assert [(e.item_id, e.outcome, e.completed_by) for e in day.dismissed] == [
        ("a", "dismissed", None)
    ]
    assert [(e.item_id, e.outcome) for e in day.done_by_you] == [("b", "done")]


async def test_dismissing_a_checked_off_item_replaces_the_check_off(rig: LedgerRig) -> None:
    seed(rig, "a")
    await rig.items.check_off("a")

    event = await rig.items.dismiss("a")

    assert event.status is None
    assert [e.group for e in history(rig)] == ["dismissed"]


async def test_checking_off_a_dismissed_item_replaces_the_dismissal(rig: LedgerRig) -> None:
    seed(rig, "a")
    await rig.items.dismiss("a")

    event = await rig.items.check_off("a")

    assert (event.status, event.dismissed_at) == ("done", None)
    assert [e.group for e in history(rig)] == ["done_by_you"]


# ---- restore ----


async def test_restoring_a_dismissed_item_returns_it_to_the_lists_and_leaves_history(
    rig: LedgerRig,
) -> None:
    seed(rig, "a")
    await rig.items.dismiss("a")
    assert await task_ids(rig) == []

    event = await rig.items.restore("a")

    assert event.dismissed_at is None
    assert await task_ids(rig) == ["a"]
    assert history(rig) == []


async def test_restoring_a_done_item_returns_it_to_the_lists(rig: LedgerRig) -> None:
    seed(rig, "a")
    await rig.items.check_off("a")

    event = await rig.items.restore("a")

    assert event.status is None
    assert history(rig) == []


async def test_restoring_a_snoozed_item_just_clears_the_snooze(rig: LedgerRig) -> None:
    seed(rig, "a")
    await rig.items.snooze("a", "next_week")
    assert await task_ids(rig) == []

    event = await rig.items.restore("a")

    assert event.snoozed_until is None
    assert await task_ids(rig) == ["a"]


async def test_restoring_an_untouched_item_changes_nothing_and_is_repeatable(
    rig: LedgerRig,
) -> None:
    seed(rig, "a")

    first = await rig.items.restore("a")
    second = await rig.items.restore("a")

    assert first == second
    assert rig.ledger.marks(["a"]) == {}


async def test_restoring_an_item_the_source_finished_leaves_it_done(rig: LedgerRig) -> None:
    await syncing(rig, [assignment("a", status="done")]).sync("canvas")

    event = await rig.items.restore("a")

    assert event.status == "done"


async def test_restoring_an_unknown_item_is_not_found(rig: LedgerRig) -> None:
    with pytest.raises(ItemNotFoundError):
        await rig.items.restore("nope")


async def test_restore_keeps_the_note_on_the_item(rig: LedgerRig) -> None:
    seed(rig, "a")
    await rig.items.set_note("a", "remember")
    await rig.items.dismiss("a")

    event = await rig.items.restore("a")

    assert event.has_note is True


# ---- snooze ----


async def test_snoozing_hides_the_item_until_the_preset_in_the_local_day(rig: LedgerRig) -> None:
    seed(rig, "a")

    event = await rig.items.snooze("a", "tomorrow_morning")

    # NOW is Nov 7 05:00 Denver; tomorrow morning is Nov 8 08:00 MST.
    assert event.snoozed_until is not None
    assert event.snoozed_until.astimezone(DENVER).isoformat() == "2026-11-08T08:00:00-07:00"
    assert await task_ids(rig) == []


async def test_a_snoozed_item_is_not_in_history(rig: LedgerRig) -> None:
    seed(rig, "a")
    await rig.items.snooze("a", "later_today")

    assert history(rig) == []


async def test_the_item_comes_back_by_itself_when_the_snooze_ends(rig: LedgerRig) -> None:
    seed(rig, "a")
    await rig.items.snooze("a", "later_today")  # NOW + 3h
    rig.clock.advance(timedelta(hours=3) - timedelta(seconds=1))
    assert await task_ids(rig) == []

    rig.clock.advance(timedelta(seconds=1))

    assert await task_ids(rig) == ["a"]
    assert (await rig.items.get("a")).snoozed_until is None


async def test_snoozing_again_replaces_the_time(rig: LedgerRig) -> None:
    seed(rig, "a")
    await rig.items.snooze("a", "next_week")

    event = await rig.items.snooze("a", "later_today")

    assert event.snoozed_until == NOW + timedelta(hours=3)


async def test_snoozing_a_dismissed_item_replaces_the_dismissal(rig: LedgerRig) -> None:
    seed(rig, "a")
    await rig.items.dismiss("a")

    event = await rig.items.snooze("a", "later_today")

    assert event.dismissed_at is None
    assert history(rig) == []


async def test_dismissing_a_snoozed_item_ends_the_snooze(rig: LedgerRig) -> None:
    seed(rig, "a")
    await rig.items.snooze("a", "later_today")

    event = await rig.items.dismiss("a")

    assert (event.snoozed_until, event.dismissed_at) == (None, NOW)


async def test_snoozing_an_unknown_item_is_not_found(rig: LedgerRig) -> None:
    with pytest.raises(ItemNotFoundError):
        await rig.items.snooze("nope", "later_today")


# ---- a re-sync -----------------------------------------------------------------------------------


async def test_a_resync_cannot_bring_back_a_dismissed_item(rig: LedgerRig) -> None:
    service = syncing(rig, [assignment("a", hours=1)], [assignment("a", hours=1)])
    await service.sync("canvas")
    await rig.items.dismiss("a")

    await service.sync("canvas")

    assert await task_ids(rig) == []
    assert (await rig.items.get("a")).dismissed_at == NOW


async def test_a_resync_cannot_bring_back_a_done_item(rig: LedgerRig) -> None:
    service = syncing(rig, [assignment("a", hours=1)], [assignment("a", hours=1)])
    await service.sync("canvas")
    await rig.items.check_off("a")

    await service.sync("canvas")

    assert (await rig.items.get("a")).status == "done"
    assert [e.group for e in history(rig)] == ["done_by_you"]


async def test_a_resync_does_not_clear_a_snooze_early(rig: LedgerRig) -> None:
    service = syncing(rig, [assignment("a", hours=1)], [assignment("a", hours=1)])
    await service.sync("canvas")
    await rig.items.snooze("a", "next_week")

    await service.sync("canvas")

    assert await task_ids(rig) == []
    assert (await rig.items.get("a")).snoozed_until is not None


async def test_a_dismissed_item_that_leaves_the_source_and_returns_stays_dismissed(
    rig: LedgerRig,
) -> None:
    service = syncing(rig, [assignment("a", hours=1)], [], [assignment("a", hours=1)])
    await service.sync("canvas")
    await rig.items.dismiss("a")

    await service.sync("canvas")
    assert [e.group for e in history(rig)] == ["dismissed"]  # not also "gone"
    await service.sync("canvas")

    assert await task_ids(rig) == []
    assert (await rig.items.get("a")).dismissed_at == NOW


# ---- filtering on every read ----


async def test_dismissed_and_snoozed_items_leave_every_agenda_read(rig: LedgerRig) -> None:
    seed(rig, "kept", "gone", "later")
    await rig.items.dismiss("gone")
    await rig.items.snooze("later", "next_week")

    assert [e.id for e in await rig.agenda.day(DAY)] == ["kept"]
    assert [e.id for e in await rig.agenda.week(DAY)] == ["kept"]
    assert [e.id for e in await rig.agenda.month(DAY)] == ["kept"]
    assert [e.id for e in await rig.agenda.between(EVERYTHING)] == ["kept"]
    assert [e.id for e in await rig.agenda.attention()] == ["kept"]
    assert [t.id for t in await rig.agenda.tasks()] == ["kept"]
    assert [n.id for n in await rig.agenda.needs_me()] == ["kept"]


async def test_undated_dismissed_and_snoozed_tasks_leave_the_lists(rig: LedgerRig) -> None:
    rig.events.upsert([make_event(id=i, kind="task", source="local") for i in ("u1", "u2", "u3")])
    await rig.items.dismiss("u1")
    await rig.items.snooze("u2", "next_week")

    assert [t.id for t in await rig.agenda.tasks()] == ["u3"]


async def test_the_summary_input_leaves_out_dismissed_and_snoozed_items(rig: LedgerRig) -> None:
    rig.events.upsert(
        [
            assignment("a", hours=1, title="Keep me"),
            assignment("b", hours=1, title="Dismissed one"),
            assignment("c", hours=1, title="Snoozed one"),
        ]
    )
    await rig.items.dismiss("b")
    await rig.items.snooze("c", "next_week")
    provider = FakeSummaryProvider(GOOD)
    service = SummaryService(
        AgendaService(rig.events, rig.clock, DENVER, rig.ledger),
        InMemorySummaryStore(),
        provider,
        rig.clock,
        DENVER,
        include_email=False,
    )

    await service.get(DAY)

    (prompt,) = provider.prompts
    assert "Keep me" in prompt
    assert "Dismissed one" not in prompt
    assert "Snoozed one" not in prompt


async def test_get_still_returns_a_hidden_item_so_the_actions_can_answer_with_it(
    rig: LedgerRig,
) -> None:
    seed(rig, "a")
    await rig.items.dismiss("a")

    assert (await rig.items.get("a")).id == "a"


# ---- migration ----


def test_a_ledger_from_before_the_columns_is_migrated_and_keeps_its_rows(rig: LedgerRig) -> None:
    with rig.engine.begin() as connection:
        connection.execute(text("ALTER TABLE item_ledger DROP COLUMN dismissed_at"))
        connection.execute(text("ALTER TABLE item_ledger DROP COLUMN snoozed_until"))
    ensure_ledger_schema(rig.engine)
    ensure_ledger_schema(rig.engine)  # running it again is harmless

    seed(rig, "a")
    asyncio.run(rig.items.dismiss("a"))

    assert [e.group for e in history(rig)] == ["dismissed"]
