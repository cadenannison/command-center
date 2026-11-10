"""What the sources did to items, kept after the items are gone: the sync side of the ledger.

One `item_ledger` row per (user, item id), made only when there is something to remember: a note,
a completion, or an item that vanished from its source. Completions are entries of the
append-only `item_completions` table (decision 0131). `record_sync` runs inside
`replace_events`' transaction, so in distributed mode it sits behind the report sink's generation
lock and a stale report writes nothing here (decisions 0120, 0121).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Engine, delete, inspect, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from command_center.core.ledger import DONE_STATUS, LOCAL_SOURCE
from command_center.core.schema import Event
from command_center.storage.sqlite_completions import (
    SOURCE,
    add_completion,
    delete_source_completions,
    ensure_completions_table,
    has_completion,
    latest_source_completion,
)
from command_center.storage.sqlite_ledger_tables import CompletionRow, LedgerBase, LedgerRow

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult

_WEATHER = "weather"  # a forecast replaced every day is not an item that "disappeared"


class LedgerRowVanishedError(Exception):
    """A delete committed between a sync's insert of a ledger row and its re-read of it."""

    def __init__(self, item_id: str) -> None:
        super().__init__(f"The ledger row of item {item_id} vanished between its insert and read")
        self.item_id = item_id


@dataclass(frozen=True)
class Seen:
    """What a replace read of a stored event before deleting it."""

    id: str
    kind: str
    title: str
    status: str | None
    anchor: datetime | None
    link: str | None


def ensure_ledger_schema(engine: Engine) -> None:
    """Create the ledger tables, or bring tables from before 0130 and 0131 up to date.

    `reopened_at` is added to an `item_ledger` made before decision 0130 (existing rows get NULL,
    which reads as "not reopened"). `item_completions` is created, and filled once from the old
    `done_at` and `done_by` columns, in the same transaction (decision 0131).
    """
    LedgerBase.metadata.create_all(engine, tables=[LedgerBase.metadata.tables["item_ledger"]])
    _add_reopened_at(engine)
    ensure_completions_table(engine)


def _add_reopened_at(engine: Engine) -> None:
    if _has_reopened_at(engine):
        return
    try:
        with engine.begin() as connection:
            if connection.dialect.name == "sqlite":
                # pysqlite does not open a transaction before DDL (see ensure_state_schema).
                connection.exec_driver_sql("BEGIN")
            # The type comes from the mapped column so a migrated table matches a fresh one
            # (TIMESTAMP WITH TIME ZONE on Postgres).
            column_type = LedgerRow.__table__.c.reopened_at.type.compile(dialect=connection.dialect)
            connection.execute(
                text(f"ALTER TABLE item_ledger ADD COLUMN reopened_at {column_type}")
            )
    except DBAPIError:
        # If the column is there, another process added it between our check and our ALTER.
        if not _has_reopened_at(engine):
            raise


def _has_reopened_at(engine: Engine) -> bool:
    columns = inspect(engine).get_columns("item_ledger")
    return any(column["name"] == "reopened_at" for column in columns)


def row_from(
    user_id: str,
    item_id: str,
    snapshot: Event | Seen,
    *,
    source: str,
) -> LedgerRow:
    """A new, empty row holding the snapshot of an item."""
    anchor = (
        snapshot.anchor
        if isinstance(snapshot, Seen)
        else (snapshot.start if snapshot.start is not None else snapshot.due)
    )
    return LedgerRow(
        user_id=user_id,
        item_id=item_id,
        source=source,
        kind=snapshot.kind,
        title=snapshot.title,
        anchor=anchor,
        link=snapshot.link,
    )


def insert_or_get(session: Session, row: LedgerRow) -> LedgerRow:
    """Insert the row unless one with its key exists, and return the stored row either way.

    A check-off can commit the same row between a sync's read and its insert; a plain `add`
    would then clash on the key and roll the whole report back (decision 0230). On Postgres a
    concurrent insert that has not committed yet makes this statement wait for it.
    """
    dialect = session.get_bind().dialect.name
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    values = {
        column.key: getattr(row, column.key)
        for column in LedgerRow.__table__.columns
        if getattr(row, column.key) is not None
    }
    session.execute(insert(LedgerRow).values(**values).on_conflict_do_nothing())
    stored = session.get(LedgerRow, (row.user_id, row.item_id), populate_existing=True)
    if stored is None:  # a delete committed between our insert and this read
        raise LedgerRowVanishedError(row.item_id)
    return stored


def is_empty(session: Session, row: LedgerRow) -> bool:
    """A row with no note, completion or disappearance carries nothing worth keeping."""
    return (
        row.note is None
        and row.gone_at is None
        and not has_completion(session, row.user_id, row.item_id)
    )


def delete_source_ledger(session: Session, source: str, user_id: str) -> int:
    """Delete the ledger rows and completion entries of a source (never `local`)."""
    if source == LOCAL_SOURCE:
        return 0
    delete_source_completions(session, source, user_id)
    statement = delete(LedgerRow).where(LedgerRow.user_id == user_id, LedgerRow.source == source)
    return cast("CursorResult[Any]", session.execute(statement)).rowcount


def record_sync(  # noqa: PLR0913, PLR0917
    session: Session,
    source: str,
    user_id: str,
    prior: Sequence[Seen],
    incoming: Sequence[Event],
    observed_at: datetime,
) -> None:
    """Note what a replace changed: items gone from the source, completions, reappearances.

    `prior` is what the replace is about to delete from its window; `incoming` is what it writes.
    An item is "gone" when it was stored and is no longer returned, unless it ever had a
    completion (finishing something is why it leaves the source). A completion entry is appended
    on every change from open to done the sync sees, including an item that arrives already
    done; syncs that keep seeing it done append nothing. An item the source reports open again
    after a completion gets `reopened_at` and keeps its entries (decisions 0122, 0131).
    """
    if source == LOCAL_SOURCE:
        return
    incoming_ids = {event.id for event in incoming}
    for seen in prior:
        if seen.id not in incoming_ids and seen.kind != _WEATHER:
            _mark_gone(session, user_id, source, seen, observed_at)
    for event in incoming:
        if event.status == DONE_STATUS:
            _append_source_completion(session, user_id, source, event, observed_at)
    open_ids = {e.id for e in incoming if e.status != DONE_STATUS}
    _mark_reopened(session, user_id, source, open_ids, observed_at)
    _clear_reappeared(session, user_id, source, incoming_ids)


def _mark_gone(session: Session, user_id: str, source: str, seen: Seen, at: datetime) -> None:
    row = session.get(LedgerRow, (user_id, seen.id))
    if row is None:
        if seen.status == DONE_STATUS:
            return  # done before the ledger saw it: leaving the source is not a removal
        row = insert_or_get(session, row_from(user_id, seen.id, seen, source=source))
    if has_completion(session, user_id, seen.id):
        return  # also a check-off that committed the row first
    row.title = seen.title
    row.gone_at = at


def _is_done_at_source(row: LedgerRow | None, latest: datetime | None) -> bool:
    """A source completion is current until a reopen at or after it."""
    if row is None or latest is None:
        return False
    return row.reopened_at is None or row.reopened_at < latest


def _append_source_completion(
    session: Session, user_id: str, source: str, event: Event, at: datetime
) -> None:
    row = session.get(LedgerRow, (user_id, event.id))
    if _is_done_at_source(row, latest_source_completion(session, user_id, event.id)):
        return
    if row is None:
        insert_or_get(session, row_from(user_id, event.id, event, source=source))
    add_completion(session, user_id, event.id, at, SOURCE)


def _mark_reopened(
    session: Session, user_id: str, source: str, open_ids: set[str], at: datetime
) -> None:
    """Stamp a source-completed item that the source now reports open; keep its entries."""
    completed = select(CompletionRow.item_id).where(
        CompletionRow.user_id == user_id, CompletionRow.completed_by == SOURCE
    )
    rows = select(LedgerRow).where(
        LedgerRow.user_id == user_id, LedgerRow.source == source, LedgerRow.item_id.in_(completed)
    )
    for row in session.scalars(rows):
        if row.item_id in open_ids and _is_done_at_source(
            row, latest_source_completion(session, user_id, row.item_id)
        ):
            row.reopened_at = at


def _clear_reappeared(session: Session, user_id: str, source: str, incoming: set[str]) -> None:
    gone = select(LedgerRow).where(
        LedgerRow.user_id == user_id,
        LedgerRow.source == source,
        LedgerRow.gone_at.is_not(None),
    )
    for row in session.scalars(gone):
        if row.item_id in incoming:
            row.gone_at = None
            if is_empty(session, row):
                session.delete(row)


__all__ = [
    "LedgerBase",
    "LedgerRow",
    "Seen",
    "delete_source_ledger",
    "ensure_ledger_schema",
    "insert_or_get",
    "is_empty",
    "record_sync",
    "row_from",
]
