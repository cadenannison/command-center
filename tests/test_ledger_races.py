"""A sync does not clash with a check-off that makes the same ledger row first (decision 0230).

The check-off is made to commit between the sync's read of the ledger row and its insert, by
wrapping `row_from`, which the sync calls right before it inserts. The first case runs on SQLite
and, with CC_TEST_POSTGRES_URL, on Postgres: it uses an item stored outside the sync's window, so
the sync holds no lock on its event row and the check-off can commit (inside the window Postgres
blocks the check-off on that lock, and the interleaving cannot be staged in one thread). The
second case is SQLite only for the same reason.
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from builders import NOW
from command_center.core.ledger import LedgerEntry
from command_center.core.windows import TimeWindow
from command_center.storage import sqlite_ledger
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import DATABASES, open_engine

EVERYTHING = TimeWindow(start=NOW - timedelta(days=400), end=NOW + timedelta(days=400))
SYNC_WINDOW = TimeWindow(start=NOW - timedelta(days=1), end=NOW + timedelta(days=3))
FAR = 24 * 10  # hours: ten days out, outside SYNC_WINDOW


@pytest.fixture(params=DATABASES)
def rig(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine(request.param, tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def sqlite_rig(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


def check_off_before_the_first_insert(rig: LedgerRig, monkeypatch: pytest.MonkeyPatch) -> None:
    real = sqlite_ledger.row_from
    seen: list[str] = []

    def racing(*args: object, **kwargs: object) -> sqlite_ledger.LedgerRow:
        if not seen:
            seen.append("done")
            assert rig.ledger.check_off("a", NOW) is True  # commits the row the sync will insert
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(sqlite_ledger, "row_from", racing)


def groups(entries: list[LedgerEntry]) -> list[str]:
    return sorted(entry.group for entry in entries)


def test_a_sync_that_finds_its_item_done_keeps_the_row_a_check_off_made_first(
    rig: LedgerRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.events.upsert([assignment("a", hours=FAR)])
    check_off_before_the_first_insert(rig, monkeypatch)

    rig.events.replace("canvas", SYNC_WINDOW, [assignment("a", hours=1, status="done")])

    (mark,) = rig.ledger.marks(["a"]).values()
    assert mark.done_by == "user"  # the check-off won the row, the sync's entry joined it
    assert groups(rig.ledger.history(EVERYTHING)) == ["done_by_source", "done_by_you"]


def test_a_sync_that_loses_an_item_keeps_the_check_off_made_first_and_does_not_call_it_gone(
    sqlite_rig: LedgerRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = sqlite_rig
    rig.events.upsert([assignment("a", hours=1)])
    check_off_before_the_first_insert(rig, monkeypatch)

    rig.events.replace("canvas", SYNC_WINDOW, [])

    (mark,) = rig.ledger.marks(["a"]).values()
    assert mark.done_by == "user"
    assert groups(rig.ledger.history(EVERYTHING)) == ["done_by_you"]
