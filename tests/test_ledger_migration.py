"""The startup migration that adds `reopened_at` to a ledger table made before decision 0130."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, bindparam, inspect, literal_column, select, text

from builders import NOW
from command_center.core.windows import TimeWindow
from command_center.storage.sqlite_items import SqliteItemLedger
from command_center.storage.sqlite_ledger import LedgerBase, ensure_ledger_schema
from command_center.storage.sqlite_types import UtcDateTime
from sink_support import DATABASES, open_engine

EVERYTHING = TimeWindow(start=NOW - timedelta(days=30), end=NOW + timedelta(days=30))
INSERT_OLD_ROW = text(
    "INSERT INTO item_ledger (user_id, item_id, source, kind, title, note, done_at, done_by) "
    "VALUES ('local', 'a', 'canvas', 'assignment', 'Essay', 'draft', :done_at, 'source')"
).bindparams(bindparam("done_at", type_=UtcDateTime))


@pytest.fixture(params=DATABASES)
def old_engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    """A database whose item_ledger table has no reopened_at column, holding one completed row."""
    for engine in open_engine(request.param, tmp_path):
        LedgerBase.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE item_completions"))
            connection.execute(text("ALTER TABLE item_ledger DROP COLUMN reopened_at"))
            connection.execute(INSERT_OLD_ROW, {"done_at": NOW})
        yield engine


def _columns(engine: Engine) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("item_ledger")}


def test_the_rig_really_starts_without_the_column(old_engine: Engine) -> None:
    assert "reopened_at" not in _columns(old_engine)


def test_the_migration_adds_reopened_at(old_engine: Engine) -> None:
    ensure_ledger_schema(old_engine)

    assert "reopened_at" in _columns(old_engine)


def test_the_migrated_column_has_the_type_of_a_fresh_one(old_engine: Engine) -> None:
    ensure_ledger_schema(old_engine)

    migrated = next(
        c for c in inspect(old_engine).get_columns("item_ledger") if c["name"] == "reopened_at"
    )
    fresh = next(
        c for c in inspect(old_engine).get_columns("item_ledger") if c["name"] == "gone_at"
    )
    assert type(migrated["type"]) is type(fresh["type"])
    assert getattr(migrated["type"], "timezone", None) == getattr(fresh["type"], "timezone", None)


def test_a_reopened_at_stamped_on_a_migrated_table_reads_back_unchanged(old_engine: Engine) -> None:
    ensure_ledger_schema(old_engine)
    stamp = NOW + timedelta(hours=3)
    with old_engine.begin() as connection:
        connection.execute(
            text("UPDATE item_ledger SET reopened_at = :at").bindparams(
                bindparam("at", type_=UtcDateTime)
            ),
            {"at": stamp},
        )

    with old_engine.connect() as connection:
        stored = connection.execute(
            select(literal_column("reopened_at", UtcDateTime)).select_from(text("item_ledger"))
        ).scalar_one()
    assert stored == stamp


def test_the_migration_keeps_existing_rows_untagged(old_engine: Engine) -> None:
    ensure_ledger_schema(old_engine)

    (entry,) = SqliteItemLedger(old_engine).history(EVERYTHING)
    assert (entry.item_id, entry.group, entry.note, entry.reopened) == (
        "a",
        "done_by_source",
        "draft",
        False,
    )


def test_the_migration_is_harmless_to_run_twice(old_engine: Engine) -> None:
    ensure_ledger_schema(old_engine)
    ensure_ledger_schema(old_engine)

    assert "reopened_at" in _columns(old_engine)
    assert len(SqliteItemLedger(old_engine).history(EVERYTHING)) == 1


def test_a_fresh_database_gets_the_column_from_create_all(tmp_path: Path) -> None:
    for engine in open_engine("sqlite", tmp_path):
        ensure_ledger_schema(engine)
        assert "reopened_at" in _columns(engine)
