"""SQLAlchemy ItemLedger: notes, check-offs, history and the user's own tasks (decision 0120).

Synced items live in the events table and local tasks (source `local`, kind `task`) too, so the
agenda reads both the same way and no sync, which only touches the sources it fetched, can prune
a task. The ledger table holds what the user did to an item; `sqlite_ledger.record_sync` holds
what the sources did. A write that makes a row reads the item, writes the row, then reads the
item again under the write lock (SQLite) or the event row's lock (Postgres), so a disconnect that
deleted the item cannot be followed by a note about it (decisions 0121, 0128).
"""

from collections.abc import Callable, Collection
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Concatenate, cast

from sqlalchemy import Engine, and_, create_engine, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from command_center.core.ledger import (
    LOCAL_SOURCE,
    ItemMark,
    LedgerEntry,
    is_local,
)
from command_center.core.schema import Event
from command_center.core.windows import TimeWindow
from command_center.storage.sqlite import (
    delete_local_event,
    ensure_event_schema,
    read_event,
    update_local_event,
    write_event,
)
from command_center.storage.sqlite_completions import (
    USER,
    add_completion,
    current_completions,
    delete_item_completions,
    has_completion,
    remove_user_completions,
)
from command_center.storage.sqlite_ledger import delete_source_ledger, is_empty, row_from
from command_center.storage.sqlite_ledger_tables import CompletionRow, LedgerRow

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult

_ID_CHUNK = 400  # stays under SQLite's bound-variable limit on old builds


def _attempt[**P](
    method: Callable[Concatenate["SqliteItemLedger", P], bool],
    ledger: "SqliteItemLedger",
    *args: P.args,
    **kwargs: P.kwargs,
) -> bool:
    try:
        return method(ledger, *args, **kwargs)
    except StaleDataError:
        return False  # a disconnect deleted the row mid-write: the item is unknown now


def _tolerating_concurrent_writes[**P](
    method: Callable[Concatenate["SqliteItemLedger", P], bool],
) -> Callable[Concatenate["SqliteItemLedger", P], bool]:
    """A disconnect that deletes the row mid-write makes the item unknown, not a server error.

    A sync that made the same row between this write's read and its insert is a unique-key clash:
    the write runs once more, and the second try finds that row (decision 0128).
    """

    @wraps(method)
    def guarded(self: "SqliteItemLedger", *args: P.args, **kwargs: P.kwargs) -> bool:
        try:
            return _attempt(method, self, *args, **kwargs)
        except IntegrityError:
            return _attempt(method, self, *args, **kwargs)

    return guarded


class SqliteItemLedger:
    """ItemLedger over one SQLAlchemy engine; events and ledger must be in one database."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine)

    def close(self) -> None:
        """Release the connection pool."""
        self._engine.dispose()

    def find(self, item_id: str, *, user_id: str = "local") -> Event | None:
        with self._sessions() as session:
            return read_event(session, item_id, user_id)

    def marks(self, item_ids: Collection[str], *, user_id: str = "local") -> dict[str, ItemMark]:
        wanted = list(item_ids)
        found: dict[str, ItemMark] = {}
        with self._sessions() as session:
            for start in range(0, len(wanted), _ID_CHUNK):
                chunk = wanted[start : start + _ID_CHUNK]
                done = current_completions(session, user_id, chunk)
                statement = select(LedgerRow).where(
                    LedgerRow.user_id == user_id, LedgerRow.item_id.in_(chunk)
                )
                for row in session.scalars(statement):
                    if row.note is not None or row.item_id in done:
                        found[row.item_id] = _mark(row, done.get(row.item_id))
        return found

    @_tolerating_concurrent_writes
    def check_off(self, item_id: str, at: datetime, *, user_id: str = "local") -> bool:
        with self._sessions.begin() as session:
            row = _known_row(session, item_id, user_id)
            if row is None:
                return False
            _lock_row(session, row)  # a disconnect that deleted the row must not leave an entry
            if not has_completion(session, user_id, item_id, USER):
                add_completion(session, user_id, item_id, at, USER)
            return True

    @_tolerating_concurrent_writes
    def undo(self, item_id: str, *, user_id: str = "local") -> bool:
        with self._sessions.begin() as session:
            row = session.get(LedgerRow, (user_id, item_id))
            if row is None:
                return read_event(session, item_id, user_id) is not None
            remove_user_completions(session, user_id, item_id)
            _drop_if_empty(session, row)
            return True

    @_tolerating_concurrent_writes
    def set_note(self, item_id: str, text: str, at: datetime, *, user_id: str = "local") -> bool:
        with self._sessions.begin() as session:
            row = _known_row(session, item_id, user_id)
            if row is None:
                return False
            row.note = text
            row.note_at = at
            return True

    @_tolerating_concurrent_writes
    def clear_note(self, item_id: str, *, user_id: str = "local") -> bool:
        with self._sessions.begin() as session:
            row = session.get(LedgerRow, (user_id, item_id))
            if row is None:
                return read_event(session, item_id, user_id) is not None
            row.note = None
            row.note_at = None
            _drop_if_empty(session, row)
            return True

    def history(self, window: TimeWindow, *, user_id: str = "local") -> list[LedgerEntry]:
        start = window.start
        end = window.end
        completed = (
            select(CompletionRow, LedgerRow)
            .join(
                LedgerRow,
                and_(
                    LedgerRow.user_id == CompletionRow.user_id,
                    LedgerRow.item_id == CompletionRow.item_id,
                ),
            )
            .where(
                CompletionRow.user_id == user_id,
                CompletionRow.completed_at >= start,
                CompletionRow.completed_at < end,
            )
        )
        gone = select(LedgerRow).where(
            LedgerRow.user_id == user_id, LedgerRow.gone_at >= start, LedgerRow.gone_at < end
        )
        entries: list[LedgerEntry] = []
        with self._sessions() as session:
            for completion, row in session.execute(completed):
                by_you = completion.completed_by == USER
                reopened = (
                    not by_you
                    and row.reopened_at is not None
                    and row.reopened_at >= completion.completed_at
                )
                group = "done_by_you" if by_you else "done_by_source"
                entries.append(_entry(row, completion.completed_at, group, reopened=reopened))
            entries.extend(
                _entry(row, row.gone_at, "gone") for row in session.scalars(gone) if row.gone_at
            )
        return sorted(entries, key=lambda e: (e.at, e.item_id, e.group))

    def save_local(self, event: Event) -> None:
        if not is_local(event):
            msg = f"Event {event.id} is not a local task"
            raise ValueError(msg)
        with self._sessions.begin() as session:
            write_event(session, event)

    def update_local(self, event: Event) -> bool:
        if not is_local(event):
            msg = f"Event {event.id} is not a local task"
            raise ValueError(msg)
        with self._sessions.begin() as session:
            return update_local_event(session, event)

    def remove_local(self, item_id: str, *, user_id: str = "local") -> bool:
        with self._sessions.begin() as session:
            if not delete_local_event(session, item_id, user_id, LOCAL_SOURCE):
                return False
            delete_item_completions(session, user_id, item_id)
            row = session.get(LedgerRow, (user_id, item_id))
            if row is not None:
                session.delete(row)
            return True

    def delete_source(self, source: str, *, user_id: str = "local") -> int:
        with self._sessions.begin() as session:
            return delete_source_ledger(session, source, user_id)


def _known_row(session: Session, item_id: str, user_id: str) -> LedgerRow | None:
    """The item's row, made from its stored event when it has none; None for an unknown item."""
    row = session.get(LedgerRow, (user_id, item_id))
    event = read_event(session, item_id, user_id, lock=True)
    if event is None:
        return row
    if row is None:
        row = row_from(user_id, item_id, event, source=event.source)
        session.add(row)
        session.flush()  # SQLite takes its write lock here; Postgres already holds the event's
        if read_event(session, item_id, user_id, lock=True) is None:
            session.delete(row)  # a disconnect deleted the item between the read and the lock
            session.flush()
            return None
    else:
        row.title = event.title
    return row


def _lock_row(session: Session, row: LedgerRow) -> None:
    """Take the row's write lock; StaleDataError (the item is unknown now) if it was deleted."""
    touched = session.execute(
        update(LedgerRow)
        .where(LedgerRow.user_id == row.user_id, LedgerRow.item_id == row.item_id)
        .values(title=LedgerRow.title)
    )
    if cast("CursorResult[Any]", touched).rowcount == 0:
        msg = "The ledger row was deleted while a write was in flight"
        raise StaleDataError(msg)


def _drop_if_empty(session: Session, row: LedgerRow) -> None:
    if is_empty(session, row):
        session.delete(row)


def _mark(row: LedgerRow, completion: tuple[str, datetime] | None) -> ItemMark:
    by, at = completion if completion is not None else (None, None)
    return ItemMark(
        item_id=row.item_id,
        has_note=row.note is not None,
        note=row.note,
        done_by="user" if by == USER else ("source" if by else None),
        done_at=at,
    )


def _entry(row: LedgerRow, at: datetime, group: str, *, reopened: bool = False) -> LedgerEntry:
    return LedgerEntry.model_validate(
        {
            "reopened": reopened,
            "item_id": row.item_id,
            "source": row.source,
            "kind": row.kind,
            "title": row.title,
            "at": at,
            "group": group,
            "note": row.note,
            "link": row.link,
        }
    )


def create_item_ledger(database_url: str) -> SqliteItemLedger:
    """Open the database at database_url; creates the events and ledger tables if missing."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(str(url.database)).parent.mkdir(parents=True, exist_ok=True)
    # Hidden parameters keep titles and note text out of error messages and logs (decision 0027).
    engine = create_engine(url, hide_parameters=True)
    ensure_event_schema(engine)
    return SqliteItemLedger(engine)


__all__ = ["SqliteItemLedger", "create_item_ledger"]
