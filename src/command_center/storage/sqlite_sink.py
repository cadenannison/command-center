"""SQLAlchemy ReportSink: a report's events, state and generation check in one transaction.

Events, `sync_states` and `source_generations` must live in the same database (they do: one
DATABASE_URL). Every statement of `apply` and `purge_stale` runs after `lock_generation`, so on
Postgres a disconnect's `bump` waits for the transaction in flight and two normalizers take turns
per source; on SQLite writers are serialised by the database. Decision 0075.
"""

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from command_center.core.ports import ApplyOutcome
from command_center.core.schema import Event
from command_center.core.sync_state import SyncState
from command_center.core.windows import TimeWindow
from command_center.storage.sqlite import (
    delete_source_events,
    ensure_event_schema,
    replace_events,
)
from command_center.storage.sqlite_generations import (
    ensure_generation_schema,
    lock_generation,
)
from command_center.storage.sqlite_ledger import delete_source_ledger
from command_center.storage.sqlite_states import (
    delete_state,
    ensure_state_schema,
    put_state,
    read_state,
)


class SqliteReportSink:
    """ReportSink over one SQLAlchemy engine (SQLite or Postgres)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine)

    def close(self) -> None:
        """Release the connection pool."""
        self._engine.dispose()

    def apply(
        self,
        generation: int,
        window: TimeWindow,
        events: Sequence[Event] | None,
        state: SyncState,
        *,
        user_id: str = "local",
    ) -> ApplyOutcome:
        source = state.source
        with self._sessions.begin() as session:
            current = lock_generation(session, source, user_id)
            if current != generation:
                return "not_current"
            stored = read_state(session, source, user_id)
            if stored is not None and stored.generation < generation:
                # Left behind by a write whose cleanup never ran: not part of this connection.
                delete_source_events(session, source, user_id)
                delete_source_ledger(session, source, user_id)
                delete_state(session, source, user_id)
                stored = None
            if stored is not None and stored.state is not None and state.at < stored.state.at:
                return "older"
            if events is not None:
                replace_events(session, source, window, events, user_id, state.at)
            put_state(session, state, user_id, generation=generation)
        return "applied"

    def purge_stale(self, source: str, *, user_id: str = "local") -> bool:
        with self._sessions.begin() as session:
            current = lock_generation(session, source, user_id)
            stored = read_state(session, source, user_id)
            if stored is None or stored.generation >= current:
                return False
            delete_source_events(session, source, user_id)
            delete_source_ledger(session, source, user_id)
            delete_state(session, source, user_id)
            return True


def create_report_sink(database_url: str) -> SqliteReportSink:
    """Open the database at database_url and make sure all three tables exist and are current."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(str(url.database)).parent.mkdir(parents=True, exist_ok=True)
    # Hidden parameters keep event and message text out of error messages and logs (decision 0027).
    engine = create_engine(url, hide_parameters=True)
    ensure_schema(engine)
    return SqliteReportSink(engine)


def ensure_schema(engine: Engine) -> None:
    """Create the three tables on a fresh database; add the generation column to an old one."""
    ensure_event_schema(engine)
    ensure_generation_schema(engine)  # before the states: an old state row is stamped from it
    ensure_state_schema(engine)


__all__ = ["SqliteReportSink", "create_report_sink", "ensure_schema"]
