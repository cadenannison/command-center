"""The completions table: every completion is its own entry, the item's state is derived (0131).

SQLite always and Postgres with CC_TEST_POSTGRES_URL (sink_support.DATABASES).
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.orm import Session

from builders import NOW
from command_center.core.ledger import LedgerEntry
from command_center.core.windows import TimeWindow
from command_center.storage.sqlite_items import SqliteItemLedger
from command_center.storage.sqlite_ledger import LedgerBase, LedgerRow, ensure_ledger_schema
from ledger_support import LedgerRig, assignment, open_ledger_rig
from queue_support import WINDOW
from sink_support import DATABASES, ok_state, open_engine

EVERYTHING = TimeWindow(start=NOW - timedelta(days=400), end=NOW + timedelta(days=400))
DONE = "done"
DAY = timedelta(days=1)


@pytest.fixture(params=DATABASES)
def rig(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine(request.param, tmp_path):
        yield open_ledger_rig(engine)


def sync(
    rig: LedgerRig, *, done: bool, after: timedelta = timedelta(0), item_id: str = "a"
) -> None:
    """One sync of canvas at `after` later than the last one, reporting item_id done or open."""
    rig.clock.advance(after)
    rig.events.replace(
        "canvas", EVERYTHING, [assignment(item_id, hours=1, status=DONE if done else None)]
    )


def history(rig: LedgerRig) -> list[LedgerEntry]:
    return rig.ledger.history(EVERYTHING)


def shape(entries: list[LedgerEntry]) -> list[tuple[str, str, bool]]:
    return [(e.at.isoformat(), e.completed_by or "-", e.reopened) for e in entries]


def completion_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count()).select_from(text("item_completions"))
        ).scalar_one()


async def test_checking_off_after_a_source_reopen_is_done_and_keeps_both_history_entries(
    rig: LedgerRig,
) -> None:
    sync(rig, done=True)
    sync(rig, done=False, after=DAY)
    sync(rig, done=False, after=DAY)

    event = await rig.items.check_off("a")

    assert event.status == DONE
    assert shape(history(rig)) == [
        (NOW.isoformat(), "source", True),
        ((NOW + 2 * DAY).isoformat(), "user", False),
    ]


def test_a_source_that_completes_an_item_twice_gets_two_entries(rig: LedgerRig) -> None:
    sync(rig, done=True)
    sync(rig, done=False, after=DAY)
    sync(rig, done=True, after=DAY)

    assert shape(history(rig)) == [
        (NOW.isoformat(), "source", True),
        ((NOW + 2 * DAY).isoformat(), "source", False),
    ]


def test_an_item_that_is_reopened_twice_tags_both_of_its_entries(rig: LedgerRig) -> None:
    for done, after in [(True, 0), (False, 1), (True, 1), (False, 1)]:
        sync(rig, done=done, after=after * DAY)

    assert [e.reopened for e in history(rig)] == [True, True]


def test_a_source_that_keeps_reporting_done_records_one_entry(rig: LedgerRig) -> None:
    for _ in range(3):
        sync(rig, done=True, after=timedelta(hours=1))

    assert shape(history(rig)) == [((NOW + timedelta(hours=1)).isoformat(), "source", False)]


async def test_undoing_a_check_off_removes_only_the_user_entry(rig: LedgerRig) -> None:
    sync(rig, done=False)
    await rig.items.check_off("a")
    sync(rig, done=True, after=DAY)
    assert [e.completed_by for e in history(rig)] == ["user", "source"]

    event = await rig.items.undo("a")

    assert [e.completed_by for e in history(rig)] == ["source"]
    assert event.status == DONE  # the source still says done


async def test_undoing_the_only_entry_leaves_no_row_behind(rig: LedgerRig) -> None:
    sync(rig, done=False)
    await rig.items.check_off("a")

    event = await rig.items.undo("a")

    assert event.status != DONE
    assert history(rig) == []
    assert rig.ledger.marks(["a"]) == {}


async def test_your_check_off_decides_the_mark_even_when_the_source_completed_it_later(
    rig: LedgerRig,
) -> None:
    sync(rig, done=False)
    await rig.items.check_off("a")
    sync(rig, done=True, after=DAY)

    mark = rig.ledger.marks(["a"])["a"]

    assert (mark.done_by, mark.done_at) == ("user", NOW)


async def test_checking_off_twice_records_one_user_entry(rig: LedgerRig) -> None:
    sync(rig, done=False)
    await rig.items.check_off("a")
    rig.clock.advance(DAY)
    await rig.items.check_off("a")

    assert shape(history(rig)) == [(NOW.isoformat(), "user", False)]


async def test_checking_off_again_after_an_undo_records_a_new_entry(rig: LedgerRig) -> None:
    sync(rig, done=False)
    await rig.items.check_off("a")
    await rig.items.undo("a")
    rig.clock.advance(DAY)
    await rig.items.check_off("a")

    assert shape(history(rig)) == [((NOW + DAY).isoformat(), "user", False)]


async def test_an_item_is_done_when_the_source_says_done_or_you_checked_it_off(
    rig: LedgerRig,
) -> None:
    sync(rig, done=True)
    assert (await rig.items.undo("a")).status == DONE  # source done, no user entry
    sync(rig, done=False, after=DAY)
    assert (await rig.items.undo("a")).status != DONE  # reopened: open again
    assert (await rig.items.check_off("a")).status == DONE  # your check-off wins


def test_disconnecting_a_source_deletes_its_completion_entries_and_only_those(
    rig: LedgerRig,
) -> None:
    sync(rig, done=True)
    sync(rig, done=False, after=DAY)
    sync(rig, done=True, after=DAY)
    rig.events.replace("gmail", EVERYTHING, [assignment("g", source="gmail", status=DONE)])
    assert completion_count(rig.engine) == 3

    assert rig.ledger.delete_source("canvas") == 1

    assert completion_count(rig.engine) == 1
    assert [e.item_id for e in history(rig)] == ["g"]


def test_a_stale_report_appends_no_completion(rig: LedgerRig) -> None:
    rig.generations.bump("canvas")
    rig.generations.bump("canvas")  # generation 0 is stale

    outcome = rig.sink.apply(0, WINDOW, [assignment("a", status=DONE)], ok_state())

    assert outcome == "not_current"
    assert completion_count(rig.engine) == 0


# ---- the startup migration -----------------------------------------------------------------------


@pytest.fixture(params=DATABASES)
def legacy(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    """A database from before 0131: completions in item_ledger.done_at/done_by, no such table."""
    for engine in open_engine(request.param, tmp_path):
        LedgerBase.metadata.create_all(engine)
        with Session(engine) as session, session.begin():
            for item_id, done_by, reopened in [("src", "source", False), ("mine", "user", False)]:
                session.add(
                    LedgerRow(
                        user_id="local",
                        item_id=item_id,
                        source="canvas",
                        kind="assignment",
                        title=f"Item {item_id}",
                        done_at=NOW,
                        done_by=done_by,
                        reopened_at=NOW + DAY if reopened else None,
                    )
                )
            session.add(
                LedgerRow(
                    user_id="local",
                    item_id="back",
                    source="canvas",
                    kind="assignment",
                    title="Item back",
                    done_at=NOW,
                    done_by="source",
                    reopened_at=NOW + DAY,
                )
            )
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE item_completions"))
        yield engine


def test_the_migration_backfills_one_entry_from_each_done_row(legacy: Engine) -> None:
    ensure_ledger_schema(legacy)

    entries = SqliteItemLedger(legacy).history(EVERYTHING)
    assert sorted((e.item_id, e.completed_by, e.reopened) for e in entries) == [
        ("back", "source", True),
        ("mine", "user", False),
        ("src", "source", False),
    ]


def test_the_migration_is_safe_to_run_twice(legacy: Engine) -> None:
    ensure_ledger_schema(legacy)
    ensure_ledger_schema(legacy)

    assert completion_count(legacy) == 3


def test_a_restart_does_not_bring_back_an_undone_check_off(legacy: Engine) -> None:
    ensure_ledger_schema(legacy)
    SqliteItemLedger(legacy).undo("mine")

    ensure_ledger_schema(legacy)

    assert {e.item_id for e in SqliteItemLedger(legacy).history(EVERYTHING)} == {"src", "back"}


def test_a_restart_does_not_bring_back_a_check_off_that_was_the_only_entry(legacy: Engine) -> None:
    ensure_ledger_schema(legacy)
    with legacy.begin() as connection:
        connection.execute(text("DELETE FROM item_completions WHERE completed_by = 'source'"))
    SqliteItemLedger(legacy).undo("mine")

    ensure_ledger_schema(legacy)

    assert completion_count(legacy) == 0


def test_the_migration_keeps_the_old_columns_readable(legacy: Engine) -> None:
    ensure_ledger_schema(legacy)

    columns = {c["name"] for c in inspect(legacy).get_columns("item_ledger")}
    assert {"done_at", "done_by"} <= columns
    with legacy.connect() as connection:
        stored = connection.execute(text("SELECT done_by FROM item_ledger WHERE item_id = 'src'"))
        assert stored.scalar_one() == "source"


def test_the_completions_table_has_the_unique_key_that_makes_recording_idempotent(
    legacy: Engine,
) -> None:
    ensure_ledger_schema(legacy)

    constraints = inspect(legacy).get_pk_constraint("item_completions")
    assert set(constraints["constrained_columns"]) == {
        "user_id",
        "item_id",
        "completed_by",
        "completed_at",
    }
