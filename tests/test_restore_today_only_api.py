"""POST /v1/items/{id}/restore refuses an earlier day's entry with 409 (decisions 0334, 0404)."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auth_rig import BASE_URL, REMOTE, AuthRig, make_auth_rig
from command_center.api import create_app
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine


@pytest.fixture
def ledger_rig(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        ledger_rig = open_ledger_rig(engine)
        ledger_rig.events.upsert([assignment("a", hours=1)])
        yield ledger_rig


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


def test_restoring_a_dismissal_from_yesterday_is_409_with_a_fixed_detail(
    rig: AuthRig, ledger_rig: LedgerRig
) -> None:
    rig.local.post("/v1/items/a/dismiss")
    ledger_rig.clock.advance(timedelta(days=1))

    response = rig.local.post("/v1/items/a/restore")

    assert response.status_code == 409
    assert response.json() == {"detail": "Only items done or dismissed today can be restored"}


def test_restoring_a_dismissal_from_today_still_works(rig: AuthRig) -> None:
    rig.local.post("/v1/items/a/dismiss")

    response = rig.local.post("/v1/items/a/restore")

    assert response.status_code == 200
    assert response.json()["dismissed_at"] is None
