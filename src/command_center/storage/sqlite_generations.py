"""SQLAlchemy GenerationStore: one counter per user and source. Same URL rules as the events."""

from pathlib import Path

from sqlalchemy import Engine, Integer, String, create_engine, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class _Base(DeclarativeBase):
    pass


class _GenerationRow(_Base):
    __tablename__ = "source_generations"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, primary_key=True)
    generation: Mapped[int] = mapped_column(Integer)


class SqliteGenerationStore:
    """GenerationStore over SQLAlchemy, correct for any number of processes sharing the database.

    The increment is one `UPDATE ... SET generation = generation + 1` statement, so two bumps
    never return the same number on SQLite or Postgres.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine)

    def close(self) -> None:
        """Release the connection pool."""
        self._engine.dispose()

    def current(self, source: str, *, user_id: str = "local") -> int:
        statement = select(_GenerationRow.generation).where(
            _GenerationRow.user_id == user_id, _GenerationRow.source == source
        )
        with self._sessions() as session:
            return session.scalars(statement).first() or 0

    def bump(self, source: str, *, user_id: str = "local") -> int:
        with self._sessions.begin() as session:
            bumped = _increment(session, source, user_id)
        if bumped is not None:
            return bumped
        try:
            with self._sessions.begin() as session:
                session.add(_GenerationRow(user_id=user_id, source=source, generation=1))
        except IntegrityError:
            pass  # another process created the row first, so the update below finds it
        else:
            return 1
        with self._sessions.begin() as session:
            bumped = _increment(session, source, user_id)
        if bumped is None:  # the row was deleted between two statements: nothing deletes rows
            msg = f"Could not bump the generation of {source!r}"
            raise RuntimeError(msg)
        return bumped


def _increment(session: Session, source: str, user_id: str) -> int | None:
    statement = (
        update(_GenerationRow)
        .where(_GenerationRow.user_id == user_id, _GenerationRow.source == source)
        .values(generation=_GenerationRow.generation + 1)
        .returning(_GenerationRow.generation)
    )
    return session.execute(statement).scalar_one_or_none()


def lock_generation(session: Session, source: str, user_id: str) -> int:
    """Read the source's generation and hold its row until the caller's transaction ends.

    The report sink calls this first, so a disconnect's `bump` waits for the transaction (and the
    transaction sees any bump that committed before it). The row is created at 0 if missing, so
    there is always one to lock; "no row" and 0 mean the same to `current`. On SQLite the UPDATE
    takes the database's write lock, which does the same job.
    """
    dialect = session.get_bind().dialect.name
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    session.execute(
        insert(_GenerationRow)
        .values(user_id=user_id, source=source, generation=0)
        .on_conflict_do_nothing()
    )
    statement = (
        update(_GenerationRow)
        .where(_GenerationRow.user_id == user_id, _GenerationRow.source == source)
        .values(generation=_GenerationRow.generation)
        .returning(_GenerationRow.generation)
    )
    return session.execute(statement).scalar_one()


def create_generation_store(database_url: str) -> SqliteGenerationStore:
    """Open the database at database_url, creating the file's directory and the table."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(str(url.database)).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, hide_parameters=True)
    ensure_generation_schema(engine)
    return SqliteGenerationStore(engine)


def ensure_generation_schema(engine: Engine) -> None:
    """Create the source_generations table if it is missing."""
    _Base.metadata.create_all(engine)


__all__ = ["SqliteGenerationStore", "create_generation_store"]
