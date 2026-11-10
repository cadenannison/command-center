"""Shared wiring for the item ledger tests: real SQL stores over one engine and a fake clock.

The database is SQLite in a temp file; with CC_TEST_POSTGRES_URL set each test also runs on
Postgres (see sink_support.DATABASES). Decisions 0120 to 0125.
"""

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine

from builders import NOW, make_event
from command_center.core.schema import Event
from command_center.core.sync_state import SyncState
from command_center.services.agenda import AgendaService
from command_center.services.items import ItemService
from command_center.storage.sqlite import SqliteEventStore
from command_center.storage.sqlite_generations import SqliteGenerationStore
from command_center.storage.sqlite_items import SqliteItemLedger
from command_center.storage.sqlite_sink import SqliteReportSink, ensure_schema
from command_center.storage.sqlite_states import SqliteSyncStateStore
from fakes import FakeClock
from worker_support import SequentialIds

DENVER = ZoneInfo("America/Denver")


@dataclass
class LedgerRig:
    """Every store a ledger test touches, over one engine, with the clock the stores stamp by."""

    engine: Engine
    clock: FakeClock
    events: SqliteEventStore
    ledger: SqliteItemLedger
    sink: SqliteReportSink
    states: SqliteSyncStateStore
    generations: SqliteGenerationStore
    agenda: AgendaService
    items: ItemService


def open_ledger_rig(engine: Engine, clock: FakeClock | None = None) -> LedgerRig:
    """Create the tables on engine and open the stores; the clock starts at builders.NOW."""
    clock = clock or FakeClock(NOW)
    ensure_schema(engine)
    events = SqliteEventStore(engine, clock)
    ledger = SqliteItemLedger(engine)
    agenda = AgendaService(events, clock, DENVER, ledger)
    return LedgerRig(
        engine=engine,
        clock=clock,
        events=events,
        ledger=ledger,
        sink=SqliteReportSink(engine),
        states=SqliteSyncStateStore(engine),
        generations=SqliteGenerationStore(engine),
        agenda=agenda,
        items=ItemService(ledger, agenda, clock, SequentialIds()),
    )


def assignment(
    item_id: str,
    *,
    source: str = "canvas",
    status: str | None = None,
    hours: int = 24,
    title: str | None = None,
) -> Event:
    """An assignment due `hours` after builders.NOW, so it is inside every sync window used here."""
    return make_event(
        id=item_id,
        source=source,
        kind="assignment",
        title=title or f"Item {item_id}",
        due=NOW + timedelta(hours=hours),
        status=status,
    )


def ok_state_at(source: str, at: object) -> SyncState:
    """An ok SyncState for source stamped at `at`."""
    return SyncState.model_validate(
        {"source": source, "status": "ok", "message": "Synced", "at": at}
    )
