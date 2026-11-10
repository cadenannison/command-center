"""A paired phone may read history but never change items or notes (decision 0120).

Concrete ids, so this holds without the route table's sample values: every item write is
refused for a phone before the handler runs, while the Mac's own browser can make it, and
GET /v1/history is a read like the agenda.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from auth_rig import BASE_URL, REMOTE, AuthRig, make_auth_rig
from builders import NOW
from command_center.api import create_app
from command_center.core.windows import TimeWindow
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine

TODAY = "2026-11-07"
AROUND_NOW = TimeWindow(start=NOW - timedelta(days=30), end=NOW + timedelta(days=30))
ITEM_WRITES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", "/v1/items", {"title": "Mine", "due": "2026-11-09T12:00:00Z"}),
    ("PATCH", "/v1/items/a", {"title": "Renamed"}),
    ("DELETE", "/v1/items/a", None),
    ("POST", "/v1/items/a/done", None),
    ("DELETE", "/v1/items/a/done", None),
    ("PUT", "/v1/items/a/notes", {"text": "fake-note-for-a-phone"}),
    ("DELETE", "/v1/items/a/notes", None),
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


@pytest.mark.parametrize(("method", "path", "body"), ITEM_WRITES)
def test_a_phone_is_refused_every_item_write_and_nothing_changes(
    rig: AuthRig, ledger_rig: LedgerRig, method: str, path: str, body: dict[str, Any] | None
) -> None:
    ledger_rig.events.upsert([assignment("a", hours=1)])
    headers = rig.bearer(rig.pair_phone().access_token)

    response = rig.remote.request(method, path, json=body, headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "A paired phone may not do this"}
    assert ledger_rig.ledger.marks(["a"]) == {}
    assert [e.id for e in ledger_rig.events.query(AROUND_NOW)] == ["a"]


def test_a_phone_without_a_token_is_refused_the_history(rig: AuthRig) -> None:
    response = rig.remote.get("/v1/history", params={"from": TODAY, "to": TODAY})
    assert response.status_code == 401


def test_a_paired_phone_can_read_history_with_notes(rig: AuthRig, ledger_rig: LedgerRig) -> None:
    ledger_rig.events.upsert([assignment("a", hours=1)])
    ledger_rig.ledger.set_note("a", "fake-note-for-the-phone", NOW)
    ledger_rig.ledger.check_off("a", NOW)
    headers = rig.bearer(rig.pair_phone().access_token)

    response = rig.remote.get("/v1/history", params={"from": TODAY, "to": TODAY}, headers=headers)

    assert response.status_code == 200
    (day,) = response.json()
    assert [(e["item_id"], e["note"]) for e in day["done_by_you"]] == [
        ("a", "fake-note-for-the-phone")
    ]


@pytest.mark.parametrize(("method", "path", "body"), ITEM_WRITES[3:])
def test_the_macs_own_browser_can_make_the_same_writes(
    rig: AuthRig,
    ledger_rig: LedgerRig,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    ledger_rig.events.upsert([assignment("a", hours=1)])
    ledger_rig.ledger.check_off("a", NOW)
    ledger_rig.ledger.set_note("a", "x", NOW)

    response = rig.local.request(method, path, json=body)

    assert response.status_code == 200, response.text
