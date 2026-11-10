"""`ItemService.marks`: the note and check-off of the given items, for the pages' controls."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from builders import NOW
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


async def test_no_ids_means_no_marks_and_no_store_call(ledger: LedgerRig) -> None:
    assert await ledger.items.marks([]) == {}


async def test_only_items_with_a_note_or_a_check_off_have_a_mark(ledger: LedgerRig) -> None:
    ledger.events.upsert([assignment("a"), assignment("b"), assignment("c")])
    await ledger.items.check_off("a")
    await ledger.items.set_note("b", "bring the form")

    marks = await ledger.items.marks(["a", "b", "c"])

    assert sorted(marks) == ["a", "b"]
    assert marks["a"].done_at == NOW
    assert marks["b"].note == "bring the form"
