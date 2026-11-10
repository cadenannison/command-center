"""A phone sees Today, Week, Month and History but gets no item controls (decision 0210)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ledger_support import LedgerRig, open_ledger_rig
from sink_support import open_engine
from web_items_support import HEADERS, ItemRig, an_event, due_soon, make_item_rig

PAGES = ["/", "/week", "/month"]
PROXIED = {"X-Forwarded-For": "100.64.0.9"}
CONTROLS = [
    'hx-post="/items/',  # Done
    'hx-delete="/items/',  # Undo, Delete note, Delete task
    'hx-put="/items/',  # Save note
    'hx-patch="/items/',  # Edit task
    'class="more"',  # the details panel with the note box and Edit/Delete
    'id="new-task"',
    'hx-post="/tasks"',
]


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def rig(ledger: LedgerRig) -> ItemRig:
    found = make_item_rig(ledger)
    found.seed(due_soon("a", title="Essay"), an_event("e"))
    return found


def phone_of(rig: ItemRig) -> TestClient:
    """The Mac's page behind a proxy: a loopback Host with a proxy header counts as a phone."""
    return TestClient(rig.client.app, base_url="http://localhost", headers=PROXIED)


def tailnet_of(rig: ItemRig) -> TestClient:
    return TestClient(rig.client.app, base_url="https://mac.tail1234.ts.net")


@pytest.mark.parametrize("path", PAGES)
def test_loopback_draws_the_item_controls(rig: ItemRig, path: str) -> None:
    html = rig.page(path)

    for marker in ('hx-post="/items/a/done', 'class="more"', 'id="new-task"'):
        assert marker in html, (path, marker)


@pytest.mark.parametrize("path", PAGES)
def test_a_proxied_request_gets_the_rows_and_no_controls(rig: ItemRig, path: str) -> None:
    response = phone_of(rig).get(path)

    assert response.status_code == 200
    assert "Essay" in response.text
    assert [m for m in CONTROLS if m in response.text] == [], path


@pytest.mark.parametrize("path", PAGES)
def test_a_tailnet_host_gets_the_rows_and_no_controls(rig: ItemRig, path: str) -> None:
    response = tailnet_of(rig).get(path)

    assert response.status_code == 200
    assert "Essay" in response.text
    assert [m for m in CONTROLS if m in response.text] == [], path


def test_a_phone_still_sees_the_priority_badge_of_a_row(rig: ItemRig) -> None:
    html = phone_of(rig).get("/").text

    assert 'class="prio"' in html


def test_a_phone_sees_a_checked_off_item_as_done_without_an_undo_button(rig: ItemRig) -> None:
    done = rig.client.post("/items/a/done?ctx=agenda", headers=HEADERS)
    assert done.status_code == 200

    html = phone_of(rig).get("/").text

    assert '<span class="chip" title="Done">done</span>' in html
    assert "Undo" not in html


def test_a_phone_sees_that_an_item_has_a_note_but_not_the_note_box(rig: ItemRig) -> None:
    saved = rig.client.put(
        "/items/a/notes?ctx=agenda", data={"text": "fake-private-note"}, headers=HEADERS
    )
    assert saved.status_code == 200

    html = phone_of(rig).get("/").text

    assert "chip-note" in html
    assert "fake-private-note" not in html
    assert "<textarea" not in html


def test_the_history_page_is_served_to_a_phone(rig: ItemRig) -> None:
    assert phone_of(rig).get("/history").status_code == 200
    assert tailnet_of(rig).get("/history").status_code == 200
