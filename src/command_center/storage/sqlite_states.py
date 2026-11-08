"""SQLAlchemy SyncStateStore: one row per user and source. Same URL rules as the event store.

Each row also carries the generation it was written under (decision 0075): the report sink stamps
it, so a row from before a disconnect can be told from one written after it.
"""

from datetime import UTC
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import Engine, Integer, String, create_engine, delete, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from command_center.core.sync_state import SyncState


class _Base(DeclarativeBase):
    pass


class _StateRow(_Base):
    __tablename__ = "sync_states"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, primary_key=True)
    # The SyncState as JSON text, parsed back through the model on every read.
    state: Mapped[str] = mapped_column(String)
    # The source's generation when the row was written; 0 for rows from before the column existed.
    generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class StoredState:
    """A row read inside a transaction: its state (None if unparsable) and its generation."""

    def __init__(self, state: SyncState | None, generation: int) -> None:
        self.state = state
        self.generation = generation


class SqliteSyncStateStore:
    """SyncStateStore over SQLAlchemy. A row that no longer parses reads as missing."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine)

    def close(self) -> None:
        """Release the connection pool."""
        self._engine.dispose()

    def put(self, state: SyncState, *, user_id: str = "local") -> None:
        # A writer that does not know about generations leaves an existing row's number alone.
        with self._sessions.begin() as session:
            put_state(session, state, user_id, generation=None)

    def get(self, source: str, *, user_id: str = "local") -> SyncState | None:
        statement = select(_StateRow.state).where(
            _StateRow.user_id == user_id, _StateRow.source == source
        )
        with self._sessions() as session:
            text_ = session.scalars(statement).first()
        return _parse(text_) if text_ is not None else None

    def delete(self, source: str, *, user_id: str = "local") -> None:
        with self._sessions.begin() as session:
            delete_state(session, source, user_id)


def put_state(session: Session, state: SyncState, user_id: str, *, generation: int | None) -> None:
    """Store state inside the caller's transaction, stamped with generation.

    `generation=None` keeps the number of an existing row (0 for a new one).
    """
    stored = state.model_copy(update={"at": state.at.astimezone(UTC)}).model_dump_json()
    row = session.get(_StateRow, (user_id, state.source))
    if row is None:
        session.add(
            _StateRow(
                user_id=user_id,
                source=state.source,
                state=stored,
                generation=generation or 0,
            )
        )
        return
    row.state = stored
    if generation is not None:
        row.generation = generation


def read_state(session: Session, source: str, user_id: str) -> StoredState | None:
    """The source's row inside the caller's transaction, or None if there is none."""
    row = session.get(_StateRow, (user_id, source))
    if row is None:
        return None
    return StoredState(_parse(row.state), row.generation)


def delete_state(session: Session, source: str, user_id: str) -> None:
    """Delete the source's row inside the caller's transaction; none stored is not an error."""
    session.execute(
        delete(_StateRow).where(_StateRow.user_id == user_id, _StateRow.source == source)
    )


def _parse(stored: str) -> SyncState | None:
    try:
        return SyncState.model_validate_json(stored)
    except ValidationError:
        return None


def create_sync_state_store(database_url: str) -> SqliteSyncStateStore:
    """Open the database at database_url, creating the file's directory and the table."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(str(url.database)).parent.mkdir(parents=True, exist_ok=True)
    # Hidden parameters keep message text out of error messages and logs (decision 0027).
    engine = create_engine(url, hide_parameters=True)
    ensure_state_schema(engine)
    return SqliteSyncStateStore(engine)


def ensure_state_schema(engine: Engine) -> None:
    """Create the sync_states table, or add the generation column to one from before 0075.

    A row that already exists was written, and kept by every disconnect's purge, under the
    source's current generation, so the new column starts at that number (0 if the source was
    never bumped or the counter table does not exist yet), not at 0.
    """
    _Base.metadata.create_all(engine)
    if _has_generation(engine):
        return
    stamp = (
        "UPDATE sync_states SET generation = COALESCE((SELECT g.generation "
        "FROM source_generations g WHERE g.user_id = sync_states.user_id "
        "AND g.source = sync_states.source), 0)"
    )
    try:
        with engine.begin() as connection:
            if connection.dialect.name == "sqlite":
                # pysqlite does not open a transaction before DDL: without this the ALTER would
                # commit alone, and a failed or interrupted stamp would be skipped at next start.
                connection.exec_driver_sql("BEGIN")
            connection.execute(
                text("ALTER TABLE sync_states ADD COLUMN generation INTEGER NOT NULL DEFAULT 0")
            )
            if inspect(connection).has_table("source_generations"):
                connection.execute(text(stamp))
    except DBAPIError:
        # Everything above is rolled back together. If the column is there, another process
        # added and stamped it between our check and our ALTER; if not, the error is real.
        if not _has_generation(engine):
            raise


def _has_generation(engine: Engine) -> bool:
    columns = inspect(engine).get_columns("sync_states")
    return any(column["name"] == "generation" for column in columns)


__all__ = ["SqliteSyncStateStore", "create_sync_state_store"]
