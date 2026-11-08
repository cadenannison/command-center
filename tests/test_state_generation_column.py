"""The generation column on sync_states: fresh databases get it, old ones gain it (0075)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from command_center.storage.sqlite_generations import (
    SqliteGenerationStore,
    ensure_generation_schema,
)
from command_center.storage.sqlite_sink import ensure_schema
from command_center.storage.sqlite_states import create_sync_state_store, ensure_state_schema
from sink_support import DATABASES, ok_state, open_engine, open_stores


@pytest.fixture(params=DATABASES)
def engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    yield from open_engine(request.param, tmp_path)


def columns(engine: Engine) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("sync_states")}


def make_old_schema(engine: Engine) -> None:
    """The sync_states table as 3e created it, with one row in it."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE sync_states (user_id VARCHAR NOT NULL, source VARCHAR NOT NULL, "
                "state VARCHAR NOT NULL, PRIMARY KEY (user_id, source))"
            )
        )
        connection.execute(
            text("INSERT INTO sync_states (user_id, source, state) VALUES (:u, :s, :state)"),
            {
                "u": "local",
                "s": "canvas",
                "state": ok_state(message="Synced 4 items").model_dump_json(),
            },
        )


def test_a_fresh_database_gets_the_column(engine: Engine) -> None:
    ensure_schema(engine)
    assert "generation" in columns(engine)


def test_an_old_database_gains_the_column_and_keeps_its_rows(engine: Engine) -> None:
    make_old_schema(engine)
    assert "generation" not in columns(engine)

    stores = open_stores(engine)

    assert "generation" in columns(engine)
    kept = stores.states.get("canvas")
    assert kept is not None
    assert kept.message == "Synced 4 items"


def test_an_old_row_takes_the_sources_current_generation(engine: Engine) -> None:
    # The disconnects of 3e purged their rows, so a row that exists belongs to the current one.
    make_old_schema(engine)
    ensure_generation_schema(engine)
    generations = SqliteGenerationStore(engine)
    generations.bump("canvas")
    generations.bump("canvas")

    stores = open_stores(engine)

    assert stores.sink.purge_stale("canvas") is False
    assert stores.states.get("canvas") is not None
    stores.generations.bump("canvas")  # a disconnect after the upgrade does make it stale
    assert stores.sink.purge_stale("canvas") is True
    assert stores.states.get("canvas") is None


def test_an_old_row_of_a_source_never_bumped_is_generation_zero(engine: Engine) -> None:
    make_old_schema(engine)
    stores = open_stores(engine)
    assert stores.sink.purge_stale("canvas") is False
    assert stores.states.get("canvas") is not None


def test_a_failed_stamp_leaves_the_table_as_it_was_and_the_setup_raises(engine: Engine) -> None:
    make_old_schema(engine)
    with engine.begin() as connection:  # a counter table the stamp cannot read
        connection.execute(
            text("CREATE TABLE source_generations (user_id VARCHAR, source VARCHAR)")
        )

    with pytest.raises(DBAPIError):
        ensure_state_schema(engine)

    assert "generation" not in columns(engine)  # not half-migrated: the next start tries again


def test_setting_up_twice_changes_nothing(engine: Engine) -> None:
    make_old_schema(engine)
    ensure_schema(engine)
    ensure_schema(engine)
    assert "generation" in columns(engine)
    assert open_stores(engine).states.get("canvas") is not None


def test_the_store_factory_upgrades_an_old_sqlite_file(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(url)
    make_old_schema(engine)
    engine.dispose()

    store = create_sync_state_store(url)

    assert store.get("canvas") is not None
    store.put(ok_state(message="Synced 5 items"))
    updated = store.get("canvas")
    assert updated is not None
    assert updated.message == "Synced 5 items"
