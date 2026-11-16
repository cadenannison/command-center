"""The one place a storage engine is built (decision 0411)."""

from sqlite3 import Connection

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import ConnectionPoolEntry

BUSY_TIMEOUT_MS = 5000


def make_engine(database_url: str) -> Engine:
    """Build an engine; SQLite gets WAL, a busy timeout and foreign keys on every connection.

    Postgres and other dialects pass through unchanged. Parameters are hidden so an error message
    never carries event or note text (decision 0027).
    """
    url = make_url(database_url)
    engine = create_engine(url, hide_parameters=True)
    if url.get_backend_name() == "sqlite":
        in_memory = url.database in (None, "", ":memory:")

        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi_connection: Connection, _record: ConnectionPoolEntry) -> None:
            cursor = dbapi_connection.cursor()
            try:
                if not in_memory:
                    cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine
