"""Shared pieces for the report sink tests: one database, all the stores over it (decision 0075).

The database is SQLite in a temp file; with CC_TEST_POSTGRES_URL set each test also runs on
Postgres, in a schema of its own that is dropped afterwards.
"""

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text

from command_center.core.sync_state import SyncState
from command_center.storage.sqlite import SqliteEventStore
from command_center.storage.sqlite_generations import SqliteGenerationStore
from command_center.storage.sqlite_sink import SqliteReportSink, ensure_schema
from command_center.storage.sqlite_states import SqliteSyncStateStore
from queue_support import START

POSTGRES_URL_ENV = "CC_TEST_POSTGRES_URL"

DATABASES = [
    pytest.param("sqlite", id="sqlite"),
    pytest.param(
        "postgres",
        id="postgres",
        marks=pytest.mark.skipif(
            not os.environ.get(POSTGRES_URL_ENV), reason=f"{POSTGRES_URL_ENV} is not set"
        ),
    ),
]


@dataclass
class Stores:
    """Every store over one engine, as the normalizer role and the api share one database."""

    engine: Engine
    sink: SqliteReportSink
    events: SqliteEventStore
    states: SqliteSyncStateStore
    generations: SqliteGenerationStore


def open_engine(kind: str, tmp_path: Path) -> Iterator[Engine]:
    """A fresh, empty database of the given kind; dropped when the iterator is finished."""
    if kind == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path / 'cc.db'}")
        yield engine
        engine.dispose()
        return
    url = os.environ[POSTGRES_URL_ENV]
    schema = f"cc_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def open_stores(engine: Engine) -> Stores:
    """Create the tables (or bring old ones up to date) and open every store on the engine."""
    ensure_schema(engine)
    return Stores(
        engine,
        SqliteReportSink(engine),
        SqliteEventStore(engine),
        SqliteSyncStateStore(engine),
        SqliteGenerationStore(engine),
    )


def ok_state(
    source: str = "canvas", message: str = "Synced 1 items", **kwargs: object
) -> SyncState:
    return SyncState.model_validate(
        {"source": source, "status": "ok", "message": message, "at": START, **kwargs}
    )
