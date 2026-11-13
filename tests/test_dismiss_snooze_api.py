"""The dismiss, snooze and restore routes and what the read routes then show (0334, 0398, 0399)."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from auth_rig import BASE_URL, REMOTE, AuthRig, make_auth_rig
from command_center.api import create_app
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine

TODAY = "2026-11-07"  # NOW is 05:00 on this day in America/Denver
WRITES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", "/v1/items/a/dismiss", None),
    ("POST", "/v1/items/a/snooze", {"preset": "later_today"}),
    ("POST", "/v1/items/a/restore", None),
]


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


def seed(ledger_rig: LedgerRig, *ids: str) -> None:
    ledger_rig.events.upsert([assignment(item, hours=1) for item in ids])


def ids(response: Any) -> list[str]:  # noqa: ANN401
    assert response.status_code == 200
    return [row["id"] for row in response.json()]


def test_dismissing_answers_with_the_item_and_its_time(rig: AuthRig, ledger_rig: LedgerRig) -> None:
    seed(ledger_rig, "a")

    response = rig.local.post("/v1/items/a/dismiss")

    assert response.status_code == 200
    assert response.json()["dismissed_at"] == "2026-11-07T12:00:00Z"


def test_dismissing_twice_answers_the_same(rig: AuthRig, ledger_rig: LedgerRig) -> None:
    seed(ledger_rig, "a")
    first = rig.local.post("/v1/items/a/dismiss").json()
    ledger_rig.clock.advance(timedelta(hours=2))

    second = rig.local.post("/v1/items/a/dismiss")

    assert second.status_code == 200
    assert second.json()["dismissed_at"] == first["dismissed_at"]


def test_snoozing_answers_with_the_end_time_computed_on_the_server(
    rig: AuthRig, ledger_rig: LedgerRig
) -> None:
    seed(ledger_rig, "a")

    response = rig.local.post("/v1/items/a/snooze", json={"preset": "tomorrow_morning"})

    assert response.json()["snoozed_until"] == "2026-11-08T15:00:00Z"  # 08:00 MST


@pytest.mark.parametrize("body", [{}, {"preset": "next_year"}, {"preset": "later_today", "x": 1}])
def test_a_bad_snooze_body_is_422(
    rig: AuthRig, ledger_rig: LedgerRig, body: dict[str, Any]
) -> None:
    seed(ledger_rig, "a")

    assert rig.local.post("/v1/items/a/snooze", json=body).status_code == 422


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_an_unknown_item_is_404_on_every_new_route(
    rig: AuthRig, method: str, path: str, body: dict[str, Any] | None
) -> None:
    response = rig.local.request(method, path, json=body)

    assert (response.status_code, response.json()["detail"]) == (404, "No such item")


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_a_phone_is_refused_the_new_writes_and_nothing_changes(
    rig: AuthRig, ledger_rig: LedgerRig, method: str, path: str, body: dict[str, Any] | None
) -> None:
    seed(ledger_rig, "a")
    phone = rig.pair_phone()

    response = rig.remote.request(method, path, json=body, headers=rig.bearer(phone.access_token))

    assert response.status_code == 403
    assert ledger_rig.ledger.marks(["a"]) == {}


def test_restoring_returns_a_dismissed_item_to_the_lists(
    rig: AuthRig, ledger_rig: LedgerRig
) -> None:
    seed(ledger_rig, "a")
    rig.local.post("/v1/items/a/dismiss")
    assert ids(rig.local.get("/v1/tasks")) == []

    response = rig.local.post("/v1/items/a/restore")

    assert response.json()["dismissed_at"] is None
    assert ids(rig.local.get("/v1/tasks")) == ["a"]


def test_every_read_route_leaves_out_dismissed_and_snoozed_items(
    rig: AuthRig, ledger_rig: LedgerRig
) -> None:
    seed(ledger_rig, "kept", "gone", "later")
    rig.local.post("/v1/items/gone/dismiss")
    rig.local.post("/v1/items/later/snooze", json={"preset": "next_week"})

    window = {"from": "2026-11-01T00:00:00Z", "to": "2026-11-30T00:00:00Z"}
    assert ids(rig.local.get("/v1/tasks")) == ["kept"]
    assert ids(rig.local.get("/v1/needs-me")) == ["kept"]
    assert ids(rig.local.get("/v1/events", params=window)) == ["kept"]
    for period in ("day", "week", "month"):
        assert ids(rig.local.get(f"/v1/agenda/{period}", params={"date": TODAY})) == ["kept"]
    assert ids(rig.local.get("/v1/attention")) == ["kept"]


def test_history_lists_dismissed_next_to_done_with_an_outcome(
    rig: AuthRig, ledger_rig: LedgerRig
) -> None:
    seed(ledger_rig, "a", "b", "c")
    rig.local.post("/v1/items/a/dismiss")
    rig.local.post("/v1/items/b/done")
    rig.local.post("/v1/items/c/snooze", json={"preset": "next_week"})

    response = rig.local.get("/v1/history", params={"from": TODAY, "to": TODAY})

    (day,) = response.json()
    assert [(e["item_id"], e["outcome"]) for e in day["dismissed"]] == [("a", "dismissed")]
    assert [(e["item_id"], e["outcome"]) for e in day["done_by_you"]] == [("b", "done")]
    assert day["gone"] == []
