"""The completions table: append-only entries, one per completion (decision 0131).

A source completion is appended on each open-to-done change a sync sees; a user check-off is
appended by the ledger and removed again by an undo, which corrects a mistake and is not a record
of what happened. Every helper runs inside the caller's transaction.
"""

from collections.abc import Collection
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Engine, delete, func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from command_center.storage.sqlite_ledger_tables import CompletionRow, LedgerRow

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult

SOURCE = "source"
USER = "user"
_ID_CHUNK = 400  # stays under SQLite's bound-variable limit on old builds
_BACKFILL = text(
    "INSERT INTO item_completions (user_id, item_id, completed_by, completed_at) "
    "SELECT user_id, item_id, done_by, done_at FROM item_ledger "
    "WHERE done_at IS NOT NULL AND done_by IN ('user', 'source')"
)


def add_completion(session: Session, user_id: str, item_id: str, at: datetime, by: str) -> bool:
    """Append an entry unless the same one is already there; True when one was added."""
    if session.get(CompletionRow, (user_id, item_id, by, at)) is not None:
        return False
    session.add(CompletionRow(user_id=user_id, item_id=item_id, completed_by=by, completed_at=at))
    return True


def has_completion(session: Session, user_id: str, item_id: str, by: str | None = None) -> bool:
    """Whether the item has any entry (by one side only, when `by` is given)."""
    statement = select(CompletionRow.item_id).where(
        CompletionRow.user_id == user_id, CompletionRow.item_id == item_id
    )
    if by is not None:
        statement = statement.where(CompletionRow.completed_by == by)
    return session.scalars(statement.limit(1)).first() is not None


def latest_source_completion(session: Session, user_id: str, item_id: str) -> datetime | None:
    """When the source last completed the item."""
    return session.scalar(
        select(func.max(CompletionRow.completed_at)).where(
            CompletionRow.user_id == user_id,
            CompletionRow.item_id == item_id,
            CompletionRow.completed_by == SOURCE,
        )
    )


def remove_user_completions(session: Session, user_id: str, item_id: str) -> int:
    """Delete the user's own entries for the item (an undo); the source's stay."""
    statement = delete(CompletionRow).where(
        CompletionRow.user_id == user_id,
        CompletionRow.item_id == item_id,
        CompletionRow.completed_by == USER,
    )
    return cast("CursorResult[Any]", session.execute(statement)).rowcount


def delete_item_completions(session: Session, user_id: str, item_id: str) -> None:
    """Delete every entry of one item (a deleted local task)."""
    session.execute(
        delete(CompletionRow).where(
            CompletionRow.user_id == user_id, CompletionRow.item_id == item_id
        )
    )


def delete_source_completions(session: Session, source: str, user_id: str) -> int:
    """Delete the entries of every item of a source (a disconnect); needs the ledger rows."""
    items = select(LedgerRow.item_id).where(
        LedgerRow.user_id == user_id, LedgerRow.source == source
    )
    # Lock the rows first: a check-off in flight holds its row, so we wait for it to commit and
    # the delete below (a new statement, a new snapshot on Postgres) sees its entry (0128, 0131).
    session.execute(items.with_for_update()).all()
    statement = delete(CompletionRow).where(
        CompletionRow.user_id == user_id, CompletionRow.item_id.in_(items)
    )
    return cast("CursorResult[Any]", session.execute(statement)).rowcount


def current_completions(
    session: Session, user_id: str, item_ids: Collection[str]
) -> dict[str, tuple[str, datetime]]:
    """Per item, who completed it: its user entry if it has one, else the source's latest."""
    wanted = list(item_ids)
    found: dict[str, tuple[str, datetime]] = {}
    for start in range(0, len(wanted), _ID_CHUNK):
        statement = select(CompletionRow).where(
            CompletionRow.user_id == user_id,
            CompletionRow.item_id.in_(wanted[start : start + _ID_CHUNK]),
        )
        for entry in session.scalars(statement):
            held = found.get(entry.item_id)
            if held is None or _outranks(entry, held):
                found[entry.item_id] = (entry.completed_by, entry.completed_at)
    return found


def _outranks(entry: CompletionRow, held: tuple[str, datetime]) -> bool:
    by, at = held
    if entry.completed_by != by:
        return entry.completed_by == USER  # your check-off decides, whatever the source did
    return entry.completed_at > at


def ensure_completions_table(engine: Engine) -> None:
    """Create item_completions and copy the old done_at/done_by of each row into it, once.

    The copy happens only in the transaction that creates the table, so running this again (or
    on every start) never brings back a check-off that was undone afterwards. A process that
    loses the race to create the table re-checks and carries on.
    """
    table = CompletionRow.__tablename__
    if inspect(engine).has_table(table):
        return
    try:
        with engine.begin() as connection:
            if connection.dialect.name == "sqlite":
                # pysqlite does not open a transaction before DDL (see ensure_state_schema).
                connection.exec_driver_sql("BEGIN")
            # checkfirst=False: a lost race must fail at CREATE, never skip it and still backfill.
            # The name is a literal because tests/test_schema_guard.py accepts nothing else (0247).
            CompletionRow.metadata.create_all(
                connection,
                tables=[CompletionRow.metadata.tables["item_completions"]],
                checkfirst=False,
            )
            connection.execute(_BACKFILL)
    except DBAPIError:
        if not inspect(engine).has_table(table):
            raise
