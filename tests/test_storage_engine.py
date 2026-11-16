"""One engine factory: pragmas on SQLite, untouched Postgres, no second create_engine path."""

import re
import sqlite3
import time
from pathlib import Path

from sqlalchemy import create_engine, text

from command_center.storage.engine import make_engine
from command_center.storage.sqlite import create_event_store
from command_center.storage.sqlite_app_settings import create_app_setting_store

STORAGE = Path(__file__).resolve().parent.parent / "src" / "command_center" / "storage"


def test_file_database_reads_back_the_pragmas(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'cc.db'}")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()


def test_memory_database_skips_wal_but_keeps_the_other_pragmas() -> None:
    engine = make_engine("sqlite://")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "memory"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()


def test_reader_is_not_blocked_by_an_open_write_transaction(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'cc.db'}"
    writer = make_engine(url)
    reader = make_engine(url)
    with writer.begin() as setup:
        setup.execute(text("CREATE TABLE blobs (b BLOB)"))
    big = b"x" * (8 * 1024 * 1024)  # larger than the page cache, so the writer spills and locks
    with writer.connect() as connection:
        connection.exec_driver_sql("BEGIN")
        connection.execute(text("INSERT INTO blobs VALUES (:b)"), {"b": big})
        started = time.monotonic()
        with reader.connect() as read:
            read.execute(text("SELECT count(*) FROM sqlite_master")).scalar()
        assert time.monotonic() - started < 1.0
        connection.rollback()
    writer.dispose()
    reader.dispose()


def test_a_store_factory_opens_its_file_in_wal(tmp_path: Path) -> None:
    path = tmp_path / "cc.db"
    create_event_store(f"sqlite:///{path}").close()
    create_app_setting_store(f"sqlite:///{path}").close()
    with sqlite3.connect(path) as raw:
        assert raw.execute("PRAGMA journal_mode").fetchone() == ("wal",)  # persists in the file


def test_postgres_url_gets_no_connect_listener() -> None:
    url = "postgresql+psycopg://fake-user@127.0.0.1:5432/fake-db"
    ours = make_engine(url)
    plain = create_engine(url)  # the dialect's own listeners are the baseline
    assert len(ours.pool.dispatch.connect) == len(plain.pool.dispatch.connect)
    assert ours.dialect.name == "postgresql"
    ours.dispose()
    plain.dispose()


def test_create_engine_appears_only_in_the_factory() -> None:
    offenders = [
        path.name
        for path in sorted(STORAGE.glob("*.py"))
        if path.name != "engine.py" and re.search(r"\bcreate_engine\b", path.read_text())
    ]
    assert offenders == []
    assert "hide_parameters=True" in (STORAGE / "engine.py").read_text()
