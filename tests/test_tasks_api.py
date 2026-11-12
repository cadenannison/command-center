"""GET /v1/tasks: ranked, read-only, with reasons, open to a paired phone (decisions 0370, 0371)."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auth_rig import BASE_URL, REMOTE, AuthRig, make_auth_rig
from builders import NOW, make_event
from command_center.api import create_app
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
            assignment("tie-b", hours=10, title="B"),
            assignment("tie-a", hours=5, title="A"),
            assignment("late", hours=-3),
            assignment("done", hours=-3),
            make_event(
                id="mail",
                source="gmail",
                kind="email",
                status="owed",
                start=NOW - timedelta(hours=2),
                link="https://mail.example/thread/1",
                title="Re: plan",
            ),
            make_event(id="meeting", kind="event", start=NOW + timedelta(hours=1)),
        ]
    )
    ledger_rig.ledger.check_off("done", NOW)


def test_tasks_are_sorted_by_priority_then_due(rig: AuthRig, ledger_rig: LedgerRig) -> None:
    seed(ledger_rig)

    response = rig.local.get("/v1/tasks")

    assert response.status_code == 200
    rows = response.json()
    assert [(r["id"], r["priority"]) for r in rows] == [
        ("late", 8),
        ("tie-a", 7),
        ("tie-b", 6),
        ("mail", 3),
        ("done", 1),
        ("far", 1),
    ]


def test_a_row_carries_the_shape_the_widget_reads(rig: AuthRig, ledger_rig: LedgerRig) -> None:
    seed(ledger_rig)

    rows = {r["id"]: r for r in rig.local.get("/v1/tasks").json()}

    assert set(rows["mail"]) == {
        "id", "title", "source", "due", "link", "done", "priority", "reasons",
    }  # fmt: skip
    assert rows["mail"]["link"] == "https://mail.example/thread/1"
    assert rows["late"]["link"] is None
    assert rows["done"]["done"] is True
    assert rows["late"]["reasons"] == [
        {"code": "overdue", "points": 8, "text": "Overdue by 3 hours"}
    ]
    assert "meeting" not in rows


def test_a_paired_phone_can_read_tasks(rig: AuthRig, ledger_rig: LedgerRig) -> None:
    seed(ledger_rig)
    headers = rig.bearer(rig.pair_phone().access_token)

    response = rig.remote.get("/v1/tasks", headers=headers)

    assert response.status_code == 200
    assert response.json()[0]["id"] == "late"


def test_a_phone_without_a_token_is_refused(rig: AuthRig) -> None:
    assert rig.remote.get("/v1/tasks").status_code == 401


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_there_is_no_write_route(rig: AuthRig, method: str) -> None:
    assert rig.local.request(method, "/v1/tasks", json={}).status_code in {404, 405}
