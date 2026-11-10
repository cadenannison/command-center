"""A note or check-off cannot outlive a disconnect, or clash with a sync, mid-write (0128).

The disconnect is made to commit between the ledger's first read of the item and its write, by
wrapping the read. SQLite only: on Postgres the same interleaving blocks on the event row's lock
(the first read locks it), so there is nothing to interleave.
"""

from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from builders import NOW
from command_center.core.schema import Event
from command_center.core.windows import TimeWindow
from command_center.storage import sqlite_items
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine

EVERYTHING = TimeWindow(start=NOW - timedelta(days=400), end=NOW + timedelta(days=400))
type Write = Callable[[LedgerRig], bool]
WRITES: dict[str, Write] = {
    "note": lambda rig: rig.ledger.set_note("a", "fake-late-note", NOW),
    "check-off": lambda rig: rig.ledger.check_off("a", NOW),
}


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


def disconnect_after_the_first_read(rig: LedgerRig, monkeypatch: pytest.MonkeyPatch) -> None:
    real = sqlite_items.read_event
    seen: list[str] = []

    def racing(session: Session, item_id: str, user_id: str, *, lock: bool = False) -> Event | None:
        event = real(session, item_id, user_id, lock=lock)
        if not seen:
            seen.append(item_id)
            rig.events.delete_source("canvas")  # the disconnect, in its own order:
            rig.ledger.delete_source("canvas")  # events first, then the ledger
        return event

    monkeypatch.setattr(sqlite_items, "read_event", racing)


@pytest.mark.parametrize("write", WRITES.values(), ids=WRITES.keys())
def test_a_write_that_loses_the_race_with_a_disconnect_makes_no_row(
    rig: LedgerRig, monkeypatch: pytest.MonkeyPatch, write: Write
) -> None:
    rig.events.upsert([assignment("a")])
    disconnect_after_the_first_read(rig, monkeypatch)

    assert write(rig) is False

    assert rig.ledger.marks(["a"]) == {}
    assert rig.ledger.history(EVERYTHING) == []


@pytest.mark.parametrize("write", WRITES.values(), ids=WRITES.keys())
def test_a_write_to_an_existing_row_that_a_disconnect_deletes_is_not_found_not_an_error(
    rig: LedgerRig, monkeypatch: pytest.MonkeyPatch, write: Write
) -> None:
    rig.events.upsert([assignment("a")])
    rig.ledger.set_note("a", "earlier", NOW)  # the row exists before the disconnect
    disconnect_after_the_first_read(rig, monkeypatch)

    assert write(rig) is False

    assert rig.ledger.marks(["a"]) == {}


def test_a_write_with_no_disconnect_still_works(rig: LedgerRig) -> None:
    rig.events.upsert([assignment("a")])

    assert rig.ledger.set_note("a", "fine", NOW) is True
    assert rig.ledger.marks(["a"])["a"].note == "fine"


def test_a_write_that_clashes_with_the_row_a_sync_just_made_runs_again_and_succeeds(
    rig: LedgerRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.events.upsert([assignment("a")])
    real = sqlite_items.read_event
    seen: list[str] = []

    def racing(session: Session, item_id: str, user_id: str, *, lock: bool = False) -> Event | None:
        event = real(session, item_id, user_id, lock=lock)
        if not seen:
            seen.append(item_id)
            # the sync commits the item as done, making the very row this write is about to insert
            rig.events.replace("canvas", EVERYTHING, [assignment("a", status="done")])
        return event

    monkeypatch.setattr(sqlite_items, "read_event", racing)

    assert rig.ledger.set_note("a", "fake-after-the-sync", NOW) is True

    (mark,) = rig.ledger.marks(["a"]).values()
    assert (mark.note, mark.done_by) == ("fake-after-the-sync", "source")
