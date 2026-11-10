"""A phone may not use the web item routes; the Mac's own browser may (decision 0153).

Concrete ids, so this holds without the route table's sample values. The web UI's own routes do
not exist for a phone, so a refused write is a 404, as for `POST /pair/code` (decision 0060).
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auth_rig import BASE_URL, REMOTE, AuthRig, make_auth_rig
from builders import NOW
from command_center.api import create_app
from command_center.core.windows import TimeWindow
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine

AROUND_NOW = TimeWindow(start=NOW - timedelta(days=30), end=NOW + timedelta(days=30))
FORM = {"title": "Fake task", "due_date": "2026-11-07", "due_time": "15:00", "label": ""}
WEB_WRITES = [
    ("POST", "/items/a/done", None),
    ("DELETE", "/items/a/done", None),
    ("PUT", "/items/a/notes", {"text": "fake-note-for-a-phone"}),
    ("DELETE", "/items/a/notes", None),
    ("PATCH", "/items/a", FORM),
    ("DELETE", "/items/a", None),
    ("POST", "/tasks", FORM),
]


@pytest.fixture
def ledger_rig(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def rig(ledger_rig: LedgerRig) -> AuthRig:
    base = make_auth_rig()
    container = replace(base.container, items=ledger_rig.items)
    app = create_app(container, remote_hosts=(REMOTE,))
    return replace(
        base,
        app=app,
        container=container,
        local=TestClient(app, base_url="http://localhost"),
        remote=TestClient(app, base_url=BASE_URL),
    )


@pytest.mark.parametrize(("method", "path", "data"), WEB_WRITES)
def test_a_phone_is_refused_every_web_item_write_and_nothing_changes(
    rig: AuthRig, ledger_rig: LedgerRig, method: str, path: str, data: dict[str, str] | None
) -> None:
    ledger_rig.events.upsert([assignment("a", hours=1)])
    headers = rig.bearer(rig.pair_phone().access_token)

    response = rig.remote.request(method, path, data=data, headers=headers)

    assert response.status_code == 404
    assert ledger_rig.ledger.marks(["a"]) == {}
    assert [e.source for e in ledger_rig.events.query(AROUND_NOW)] == ["canvas"]


def test_the_macs_own_browser_can_check_off_through_the_full_app(
    rig: AuthRig, ledger_rig: LedgerRig
) -> None:
    ledger_rig.events.upsert([assignment("a", hours=1)])

    response = rig.local.post("/items/a/done", headers=rig.csrf())

    assert response.status_code == 200
    assert "a" in ledger_rig.ledger.marks(["a"])


def test_the_history_page_needs_a_token_from_a_phone(rig: AuthRig) -> None:
    assert rig.remote.get("/history").status_code == 401


def test_a_paired_phone_may_read_the_history_page_like_the_other_pages(rig: AuthRig) -> None:
    headers = rig.bearer(rig.pair_phone().access_token)

    assert rig.remote.get("/history", headers=headers).status_code == 200
