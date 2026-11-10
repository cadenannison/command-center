"""The ledger's two tables (decisions 0120, 0131).

`item_ledger` holds one row per item the user or a source left a mark on: a snapshot of the item
(so history outlives the event), its note, when it left its source and when a source last
reopened it. `item_completions` is append-only: one entry per completion, by the source or by
the user. The old `item_ledger.done_at` and `done_by` columns stay readable but are no longer
written; the migration copies them into `item_completions` once.
"""

from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from command_center.storage.sqlite_types import UtcDateTime


class LedgerBase(DeclarativeBase):
    """Declarative base of the ledger tables, kept apart from the events table's."""


class LedgerRow(LedgerBase):
    """One item's memory. `source`, `kind`, `title`, `anchor` and `link` are a snapshot."""

    __tablename__ = "item_ledger"
    __table_args__ = (
        Index("ix_item_ledger_done", "user_id", "done_at"),
        Index("ix_item_ledger_gone", "user_id", "gone_at"),
        Index("ix_item_ledger_source", "user_id", "source"),
    )

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    anchor: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    link: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )  # read-only since 0131
    done_by: Mapped[str | None] = mapped_column(String, nullable=True)  # read-only since 0131
    gone_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class CompletionRow(LedgerBase):
    """One completion of an item. The key makes recording the same completion twice a no-op."""

    __tablename__ = "item_completions"
    __table_args__ = (Index("ix_item_completions_at", "user_id", "completed_at"),)

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(String, primary_key=True)
    completed_by: Mapped[str] = mapped_column(String, primary_key=True)  # "source" or "user"
    completed_at: Mapped[datetime] = mapped_column(UtcDateTime, primary_key=True)
