"""GET /v1/needs-me: shape, order, cap, read-only, token required (decisions 0385, 0386)."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auth_rig import BASE_URL, REMOTE, AuthRig, make_auth_rig
from builders import NOW, make_event
from command_center.api import create_app
from command_center.core.needs_me import NEEDS_ME_LIMIT
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine


@pytest.fixture
def ledger_rig(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def rig(ledger_rig: LedgerRig) -> AuthRig:
    base = make_auth_rig()
    container = replace(base.container, agenda=ledger_rig.agenda, items=ledger_rig.items)
    app = create_app(container, remote_hosts=(REMOTE,))
    return replace(
        base,
        app=app,
        container=container,
        local=TestClient(app, base_url="http://localhost"),
        remote=TestClient(app, base_url=BASE_URL),
    )


def seed(ledger_rig: LedgerRig) -> None:
    ledger_rig.events.upsert(
        [
            assignment("far", hours=24 * 20),
            assignment("soon", hours=5),
            assignment("late", hours=-3),
            assignment("checked", hours=-3),
            make_event(
                id="mail",
                source="gmail",
                kind="email",
                status="overdue",
                start=NOW - timedelta(hours=2),
                link="https://mail.example/thread/1",
                title="Re: plan",
            ),
            make_event(id="meeting", kind="event", start=NOW + timedelta(hours=1)),
            make_event(id="next-week", kind="event", start=NOW + timedelta(days=5)),
        ]
    )
    ledger_rig.ledger.check_off("checked", NOW)


def test_rows_are_sorted_and_checked_off_items_are_left_out(
    rig: AuthRig, ledger_rig: LedgerRig
) -> None:
    seed(ledger_rig)

    response = rig.local.get("/v1/needs-me")

    assert response.status_code == 200
    assert [(r["id"], r["priority"]) for r in response.json()] == [
        ("late", 8),
        ("soon", 7),
        ("mail", 5),
        ("meeting", 4),
    ]


def test_a_row_carries_the_shape_the_widget_reads(rig: AuthRig, ledger_rig: LedgerRig) -> None:
    seed(ledger_rig)

    rows = {r["id"]: r for r in rig.local.get("/v1/needs-me").json()}

    assert set(rows["mail"]) == {
        "id", "kind", "title", "source", "at", "link", "priority", "reasons",
    }  # fmt: skip
    assert rows["mail"]["link"] == "https://mail.example/thread/1"
    assert rows["mail"]["kind"] == "email"
    assert rows["late"]["link"] is None
    assert rows["late"]["reasons"] == [
        {"code": "overdue", "points": 8, "text": "Overdue by 3 hours"}
    ]


def test_the_list_is_capped(rig: AuthRig, ledger_rig: LedgerRig) -> None:
    ledger_rig.events.upsert([assignment(f"t{i:02}", hours=-(i + 1)) for i in range(30)])

    rows = rig.local.get("/v1/needs-me").json()

    assert len(rows) == NEEDS_ME_LIMIT
    assert rows[0]["id"] == "t29"  # equal priority: earliest due first


def test_a_paired_phone_can_read_it(rig: AuthRig, ledger_rig: LedgerRig) -> None:
    seed(ledger_rig)
    headers = rig.bearer(rig.pair_phone().access_token)

    response = rig.remote.get("/v1/needs-me", headers=headers)

    assert response.status_code == 200
    assert response.json()[0]["id"] == "late"


def test_a_phone_without_a_token_is_refused(rig: AuthRig) -> None:
    assert rig.remote.get("/v1/needs-me").status_code == 401


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_there_is_no_write_route(rig: AuthRig, method: str) -> None:
    assert rig.local.request(method, "/v1/needs-me", json={}).status_code in {404, 405}
