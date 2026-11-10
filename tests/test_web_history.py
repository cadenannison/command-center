"""The History page: one day's completions and disappearances, with notes (decision 0153)."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from markupsafe import escape

from command_center.core.schema import Event
from command_center.services.sync import SyncService
from fake_adapter import FakeAdapter
from fakes import InMemorySecretStore
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine
from web_items_support import HEADERS, TODAY, ItemRig, due_soon, make_item_rig, section

DONE = "done"


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


def synced_rig(ledger: LedgerRig, *steps: list[Event]) -> tuple[ItemRig, SyncService]:
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", "fake-token-12345678")
    adapter = FakeAdapter("canvas", script=list(steps))
    sync = SyncService(
        {"canvas": adapter}, secrets, ledger.events, ledger.clock, ledger=ledger.ledger
    )
    return make_item_rig(ledger, sync=sync), sync


def test_an_empty_day_shows_the_three_groups_with_nothing_in_them(ledger: LedgerRig) -> None:
    html = make_item_rig(ledger).page("/history")

    assert "Nothing you checked off on this day." in section(html, "h-done_by_you")
    assert "Nothing the sources reported done on this day." in section(html, "h-done_by_source")
    assert "Nothing left its source on this day." in section(html, "h-gone")


def test_the_page_defaults_to_today_and_a_date_picks_another_day(ledger: LedgerRig) -> None:
    rig = make_item_rig(ledger)

    assert "History: Sat 7 Nov 2026" in rig.page("/history")
    assert "History: Sun 1 Nov 2026" in rig.page("/history?date=2026-11-01")
    assert 'value="2026-11-01"' in rig.page("/history?date=2026-11-01")


def test_a_bad_date_is_422(ledger: LedgerRig) -> None:
    assert make_item_rig(ledger).client.get("/history?date=soon").status_code == 422


def test_an_item_you_checked_off_is_listed_under_completed_by_you_with_its_time(
    ledger: LedgerRig,
) -> None:
    rig = make_item_rig(ledger)
    rig.seed(due_soon("a", title="Essay"))
    rig.client.post("/items/a/done", headers=HEADERS)

    html = rig.page("/history")

    mine = section(html, "h-done_by_you")
    assert "Essay" in mine
    assert "05:00" in mine  # NOW is 05:00 in America/Denver
    assert "Essay" not in section(html, "h-done_by_source")
    assert "Essay" not in section(html, "h-gone")


def test_the_page_shows_the_note_of_each_entry_escaped(ledger: LedgerRig) -> None:
    rig = make_item_rig(ledger)
    rig.seed(due_soon("a", title="<i>Essay</i>"))
    note = '<b>bring</b> the form & the "stamp"'
    rig.client.put("/items/a/notes", data={"text": note}, headers=HEADERS)
    rig.client.post("/items/a/done", headers=HEADERS)

    mine = section(rig.page("/history"), "h-done_by_you")

    assert str(escape(note)) in mine
    assert "<b>bring" not in mine
    assert "&lt;i&gt;Essay&lt;/i&gt;" in mine


async def test_an_item_the_source_finished_is_listed_under_completed_at_the_source(
    ledger: LedgerRig,
) -> None:
    rig, sync = synced_rig(ledger, [assignment("s", status=DONE, title="Handed in")])
    await sync.sync("canvas")

    html = rig.page("/history")

    assert "Handed in" in section(html, "h-done_by_source")
    assert "canvas" in section(html, "h-done_by_source")
    assert "later reopened" not in html


async def test_an_item_the_source_reopened_is_tagged_later_reopened_on_its_original_day(
    ledger: LedgerRig,
) -> None:
    rig, sync = synced_rig(
        ledger,
        [assignment("s", status=DONE, title="Resubmit")],
        [assignment("s", title="Resubmit")],
    )
    await sync.sync("canvas")
    ledger.clock.advance(timedelta(days=2))
    await sync.sync("canvas")

    on_the_day = section(rig.page(f"/history?date={TODAY}"), "h-done_by_source")
    later = section(rig.page("/history?date=2026-11-09"), "h-done_by_source")

    assert "Resubmit" in on_the_day
    assert "later reopened" in on_the_day
    assert "Resubmit" not in later


async def test_an_item_that_disappeared_from_its_source_is_listed_as_gone(
    ledger: LedgerRig,
) -> None:
    rig, sync = synced_rig(
        ledger, [assignment("a"), assignment("b", title="Dropped")], [assignment("a")]
    )
    await sync.sync("canvas")
    ledger.clock.advance(timedelta(hours=2))
    await sync.sync("canvas")

    html = rig.page("/history")

    assert "Dropped" in section(html, "h-gone")
    assert "Dropped" not in section(html, "h-done_by_you")


def test_a_link_that_is_not_http_is_not_made_clickable(ledger: LedgerRig) -> None:
    rig = make_item_rig(ledger)
    rig.seed(assignment("a", title="Linked").model_copy(update={"link": "javascript:alert(1)"}))
    rig.client.post("/items/a/done", headers=HEADERS)

    html = rig.page("/history")

    assert "javascript:" not in html
    assert "Linked" in section(html, "h-done_by_you")
