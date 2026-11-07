"""SQLAlchemy EventStore. SQLite by default; any SQLAlchemy URL (Postgres later) works unchanged."""

from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    DateTime,
    Dialect,
    Engine,
    Index,
    String,
    TypeDecorator,
    and_,
    create_engine,
    or_,
    select,
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from command_center.core.schema import Event, EventKind
from command_center.core.windows import TimeWindow


class _UtcDateTime(TypeDecorator[datetime]):
    """Stores instants as UTC and returns them timezone-aware (SQLite drops the zone itself)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,  # noqa: ARG002
    ) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            msg = "Refusing to store a naive datetime"
            raise ValueError(msg)
        return value.astimezone(UTC)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,  # noqa: ARG002
    ) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class _Base(DeclarativeBase):
    pass


class _EventRow(_Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_user_anchor", "user_id", "anchor"),)

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    start: Mapped[datetime | None] = mapped_column(_UtcDateTime, nullable=True)
    end: Mapped[datetime | None] = mapped_column(_UtcDateTime, nullable=True)
    due: Mapped[datetime | None] = mapped_column(_UtcDateTime, nullable=True)
    # The event's time (start, else due): a column so the window query and ordering use an index.
    anchor: Mapped[datetime | None] = mapped_column(_UtcDateTime, nullable=True)
    urgency: Mapped[int]
    link: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    raw: Mapped[dict[str, object]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(_UtcDateTime)


class SqliteEventStore:
    """EventStore over SQLAlchemy; matching rules are those of docs/contracts/core.md."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine)

    def close(self) -> None:
        """Release the connection pool."""
        self._engine.dispose()

    def upsert(self, events: Sequence[Event], *, user_id: str = "local") -> int:
        for event in events:
            if event.user_id != user_id:
                msg = f"Event {event.id} has user_id {event.user_id!r}, expected {user_id!r}"
                raise ValueError(msg)
        # Last one wins when a batch repeats an id, like replaying the batch in order.
        distinct = {event.id: event for event in events}
        with self._sessions.begin() as session:
            for event in distinct.values():
                session.merge(_to_row(event))
        return len(distinct)

    def query(
        self,
        window: TimeWindow,
        kinds: Collection[EventKind] | None = None,
        *,
        user_id: str = "local",
    ) -> list[Event]:
        window_start = window.start.astimezone(UTC)
        window_end = window.end.astimezone(UTC)
        is_span = and_(_EventRow.end.is_not(None), _EventRow.end > _EventRow.anchor)
        spans_window = and_(is_span, _EventRow.anchor < window_end, _EventRow.end > window_start)
        point_in_window = and_(
            or_(_EventRow.end.is_(None), _EventRow.end <= _EventRow.anchor),
            _EventRow.anchor >= window_start,
            _EventRow.anchor < window_end,
        )
        statement = (
            select(_EventRow)
            .where(
                _EventRow.user_id == user_id,
                _EventRow.anchor.is_not(None),
                or_(spans_window, point_in_window),
            )
            .order_by(_EventRow.anchor, _EventRow.id)
        )
        if kinds is not None:
            statement = statement.where(_EventRow.kind.in_(list(kinds)))
        with self._sessions() as session:
            return [_to_event(row) for row in session.scalars(statement)]


def create_event_store(database_url: str) -> SqliteEventStore:
    """Open the database at database_url, creating the file's directory and the tables."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(str(url.database)).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    _Base.metadata.create_all(engine)
    return SqliteEventStore(engine)


def _to_row(event: Event) -> _EventRow:
    anchor = event.start if event.start is not None else event.due
    return _EventRow(
        user_id=event.user_id,
        id=event.id,
        source=event.source,
        kind=event.kind,
        title=event.title,
        start=event.start,
        end=event.end,
        due=event.due,
        anchor=anchor,
        urgency=event.urgency,
        link=event.link,
        status=event.status,
        raw=event.model_dump(mode="json")["raw"],
        fetched_at=event.fetched_at,
    )


def _to_event(row: _EventRow) -> Event:
    return Event.model_validate(
        {
            "id": row.id,
            "user_id": row.user_id,
            "source": row.source,
            "kind": row.kind,
            "title": row.title,
            "start": row.start,
            "end": row.end,
            "due": row.due,
            "urgency": row.urgency,
            "link": row.link,
            "status": row.status,
            "raw": row.raw,
            "fetched_at": row.fetched_at,
        }
    )
