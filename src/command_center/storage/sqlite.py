"""SQLAlchemy EventStore. SQLite by default; any SQLAlchemy URL (Postgres later) works unchanged."""

from collections.abc import Callable, Collection, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import (
    JSON,
    Engine,
    Index,
    String,
    and_,
    create_engine,
    delete,
    or_,
    select,
    update,
)
from sqlalchemy.engine import CursorResult, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from command_center.core.ports import Clock
from command_center.core.schema import Event, EventKind
from command_center.core.windows import TimeWindow
from command_center.storage.sqlite_ledger import (
    Seen,
    ensure_ledger_schema,
    record_sync,
)
from command_center.storage.sqlite_types import UtcDateTime


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
    start: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    end: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    due: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # The event's time (start, else due): a column so the window query and ordering use an index.
    anchor: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    urgency: Mapped[int]
    link: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    raw: Mapped[dict[str, object]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SqliteEventStore:
    """EventStore over SQLAlchemy; matching rules are those of docs/contracts/core.md."""

    def __init__(self, engine: Engine, clock: Clock | None = None) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine)
        self._now: Callable[[], datetime] = (
            clock.now if clock is not None else lambda: datetime.now(UTC)
        )

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

    def replace(
        self,
        source: str,
        window: TimeWindow,
        events: Sequence[Event],
        *,
        user_id: str = "local",
    ) -> int:
        # One transaction: a failure while writing rolls the delete back too.
        with self._sessions.begin() as session:
            return replace_events(session, source, window, events, user_id, self._now())

    def delete_source(self, source: str, *, user_id: str = "local") -> int:
        with self._sessions.begin() as session:
            return delete_source_events(session, source, user_id)

    def query(
        self,
        window: TimeWindow,
        kinds: Collection[EventKind] | None = None,
        *,
        user_id: str = "local",
    ) -> list[Event]:
        statement = (
            select(_EventRow)
            .where(_EventRow.user_id == user_id, _matches_window(window))
            .order_by(_EventRow.anchor, _EventRow.id)
        )
        if kinds is not None:
            statement = statement.where(_EventRow.kind.in_(list(kinds)))
        with self._sessions() as session:
            return [_to_event(row) for row in session.scalars(statement)]

    def undated_open(
        self,
        kinds: Collection[EventKind],
        limit: int,
        *,
        user_id: str = "local",
    ) -> list[Event]:
        if limit < 1:
            return []
        statement = (
            select(_EventRow)
            .where(
                _EventRow.user_id == user_id,
                _EventRow.anchor.is_(None),
                _EventRow.kind.in_(list(kinds)),
                or_(_EventRow.status.is_(None), _EventRow.status != "done"),
            )
            .order_by(_EventRow.fetched_at.desc(), _EventRow.id)
            .limit(limit)
        )
        with self._sessions() as session:
            return [_to_event(row) for row in session.scalars(statement)]


def replace_events(  # noqa: PLR0913, PLR0917
    session: Session,
    source: str,
    window: TimeWindow,
    events: Sequence[Event],
    user_id: str,
    observed_at: datetime,
) -> int:
    """Swap the source's events in window for events inside the caller's transaction.

    The rules of `EventStore.replace`; a ValueError (an event of another user or source) is
    raised before anything is written. Shared with the report sink, which adds more statements
    to the same transaction (decision 0075). The ledger notes, in that same transaction, what
    the swap removed or completed, stamped `observed_at` (decisions 0120, 0121).
    """
    for event in events:
        if event.user_id != user_id:
            msg = f"Event {event.id} has user_id {event.user_id!r}, expected {user_id!r}"
            raise ValueError(msg)
        if event.source != source:
            msg = f"Event {event.id} has source {event.source!r}, expected {source!r}"
            raise ValueError(msg)
    distinct = {event.id: event for event in events}
    in_window = (_EventRow.user_id == user_id, _EventRow.source == source, _matches_window(window))
    # Lock the window's event rows before record_sync touches ledger rows: a check-off locks event
    # then ledger row, so for these rows both orders agree. Incoming events outside the window are
    # not locked here (decisions 0128, 0233).
    stored = select(_EventRow).where(*in_window).with_for_update()
    prior = [_to_seen(row) for row in session.scalars(stored)]
    record_sync(session, source, user_id, prior, list(distinct.values()), observed_at)
    session.execute(delete(_EventRow).where(*in_window))
    for event in distinct.values():
        session.merge(_to_row(event))
    return len(distinct)


def delete_source_events(session: Session, source: str, user_id: str) -> int:
    """Delete every event of the source (dated or not) inside the caller's transaction."""
    statement = delete(_EventRow).where(_EventRow.user_id == user_id, _EventRow.source == source)
    return cast("CursorResult[Any]", session.execute(statement)).rowcount


def _matches_window(window: TimeWindow) -> ColumnElement[bool]:
    """The one rule for "an event is in window", shared by query and replace (core.md)."""
    window_start = window.start.astimezone(UTC)
    window_end = window.end.astimezone(UTC)
    is_span = and_(_EventRow.end.is_not(None), _EventRow.end > _EventRow.anchor)
    spans_window = and_(is_span, _EventRow.anchor < window_end, _EventRow.end > window_start)
    point_in_window = and_(
        or_(_EventRow.end.is_(None), _EventRow.end <= _EventRow.anchor),
        _EventRow.anchor >= window_start,
        _EventRow.anchor < window_end,
    )
    return and_(_EventRow.anchor.is_not(None), or_(spans_window, point_in_window))


def read_event(session: Session, item_id: str, user_id: str, *, lock: bool = False) -> Event | None:
    """The stored event with this id inside the caller's transaction, or None.

    Always a fresh read (never the session's cached row). With `lock`, Postgres locks the row
    until the transaction ends, so a disconnect's delete of it waits (decision 0128); SQLite has
    no row locks and ignores it.
    """
    statement = select(_EventRow).where(_EventRow.user_id == user_id, _EventRow.id == item_id)
    if lock:
        statement = statement.with_for_update()
    row = session.scalars(statement.execution_options(populate_existing=True)).first()
    return None if row is None else _to_event(row)


def write_event(session: Session, event: Event) -> None:
    """Insert or replace one event inside the caller's transaction."""
    session.merge(_to_row(event))


def update_local_event(session: Session, event: Event) -> bool:
    """Change a stored event of the same key and source; False, writing nothing, if it is gone.

    An UPDATE never inserts, so a delete that committed first stays a delete (decision 0231).
    """
    changed = _to_row(event)
    values = {
        column.key: getattr(changed, column.key)
        for column in _EventRow.__table__.columns
        if column.key not in {"user_id", "id", "source"}
    }
    statement = (
        update(_EventRow)
        .where(
            _EventRow.user_id == event.user_id,
            _EventRow.id == event.id,
            _EventRow.source == event.source,
        )
        .values(**values)
    )
    return cast("CursorResult[Any]", session.execute(statement)).rowcount > 0


def delete_local_event(session: Session, item_id: str, user_id: str, source: str) -> bool:
    """Delete one stored event of `source`; False when there is none."""
    statement = delete(_EventRow).where(
        _EventRow.user_id == user_id, _EventRow.id == item_id, _EventRow.source == source
    )
    return cast("CursorResult[Any]", session.execute(statement)).rowcount > 0


def create_event_store(database_url: str, clock: Clock | None = None) -> SqliteEventStore:
    """Open the database at database_url, creating the file's directory and the tables.

    `clock` stamps what the ledger notes during a replace; without one the store reads the
    system clock.
    """
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(str(url.database)).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, hide_parameters=True)  # error text must not carry event content
    ensure_event_schema(engine)
    return SqliteEventStore(engine, clock)


def ensure_event_schema(engine: Engine) -> None:
    """Create the events table and the ledger table next to it if they are missing."""
    _Base.metadata.create_all(engine)
    ensure_ledger_schema(engine)


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


def _to_seen(row: _EventRow) -> Seen:
    return Seen(
        id=row.id,
        kind=row.kind,
        title=row.title,
        status=row.status,
        anchor=row.anchor,
        link=row.link,
    )
