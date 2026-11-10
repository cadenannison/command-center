"""SQLAlchemy SummaryStore: one row per user and day. Same URL rules as the event store."""

from datetime import date
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import Date, Engine, String, create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from command_center.core.summary import DailySummary


class _Base(DeclarativeBase):
    pass


class _SummaryRow(_Base):
    __tablename__ = "summaries"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    # The DailySummary as JSON text; parsed back through the model on every read.
    summary: Mapped[str] = mapped_column(String)


class SqliteSummaryStore:
    """SummaryStore over SQLAlchemy. A row that no longer parses reads as missing."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine)

    def close(self) -> None:
        """Release the connection pool."""
        self._engine.dispose()

    def get(self, day: date, *, user_id: str = "local") -> DailySummary | None:
        statement = select(_SummaryRow.summary).where(
            _SummaryRow.user_id == user_id, _SummaryRow.day == day
        )
        with self._sessions() as session:
            return _parse(session.scalars(statement).first())

    def put(self, day: date, summary: DailySummary, *, user_id: str = "local") -> None:
        row = _SummaryRow(user_id=user_id, day=day, summary=summary.model_dump_json())
        with self._sessions.begin() as session:
            session.merge(row)

    def delete(self, day: date, *, user_id: str = "local") -> None:
        statement = delete(_SummaryRow).where(
            _SummaryRow.user_id == user_id, _SummaryRow.day == day
        )
        with self._sessions.begin() as session:
            session.execute(statement)

    def latest_before(self, day: date, *, user_id: str = "local") -> DailySummary | None:
        statement = (
            select(_SummaryRow.summary)
            .where(_SummaryRow.user_id == user_id, _SummaryRow.day < day)
            .order_by(_SummaryRow.day.desc())
            .limit(1)
        )
        with self._sessions() as session:
            return _parse(session.scalars(statement).first())


def _parse(text: str | None) -> DailySummary | None:
    if text is None:
        return None
    try:
        return DailySummary.model_validate_json(text)
    except ValidationError:
        return None


def create_summary_store(database_url: str) -> SqliteSummaryStore:
    """Open the database at database_url, creating the file's directory and the table."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(str(url.database)).parent.mkdir(parents=True, exist_ok=True)
    # Hidden parameters keep summary text out of error messages and logs (decision 0027).
    engine = create_engine(url, hide_parameters=True)
    _Base.metadata.create_all(engine)
    return SqliteSummaryStore(engine)
