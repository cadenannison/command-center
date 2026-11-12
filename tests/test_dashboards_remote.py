"""A paired phone may read dashboards and display settings and may write neither (decision 0357)."""

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from auth_rig import BASE_URL, REMOTE, make_auth_rig
from builders import NOW
from command_center.api import create_app
from command_center.services.dashboards import DashboardService
from command_center.storage.sqlite_dashboards import (
    create_dashboard_store,
    create_display_settings_store,
)
from dashboard_support import DISPLAY, SeqIds, dashboard_body
from fakes import FakeClock

PHONE_DENIED = {"detail": "A paired phone may not do this"}


def test_a_phone_reads_but_every_write_is_403_and_stores_nothing(tmp_path: Path) -> None:
    rig = make_auth_rig()
    url = f"sqlite:///{tmp_path / 'cc.db'}"
    service = DashboardService(
        create_dashboard_store(url), create_display_settings_store(url), FakeClock(NOW), SeqIds()
    )
    app = create_app(replace(rig.container, dashboards=service), remote_hosts=(REMOTE,))
    local = TestClient(app, base_url="http://localhost")
    remote = TestClient(app, base_url=BASE_URL)
    headers = rig.bearer(rig.pair_phone().access_token)
    assert local.post("/v1/dashboards", json=dashboard_body()).status_code == 201

    assert [d["id"] for d in remote.get("/v1/dashboards", headers=headers).json()] == ["d1"]
    assert remote.get("/v1/dashboards/d1", headers=headers).status_code == 200
    assert remote.get("/v1/display-settings", headers=headers).json()["revision"] == 0

    match = {**headers, "If-Match": '"1"'}
    refused = [
        remote.post("/v1/dashboards", json=dashboard_body("Phone"), headers=headers),
        remote.put("/v1/dashboards/d1", json=dashboard_body("Phone"), headers=match),
        remote.put("/v1/dashboards/order", json={"ids": ["d1"]}, headers=headers),
        remote.delete("/v1/dashboards/d1", headers=match),
        remote.put("/v1/display-settings", json=DISPLAY, headers={**headers, "If-Match": '"0"'}),
    ]
    assert [r.status_code for r in refused] == [403] * 5
    assert all(r.json() == PHONE_DENIED for r in refused)
    assert [(d["name"], d["revision"]) for d in local.get("/v1/dashboards").json()] == [("Main", 1)]
    assert local.get("/v1/display-settings").json()["revision"] == 0


def test_without_a_token_the_dashboard_routes_are_401() -> None:
    remote = make_auth_rig().remote
    assert remote.get("/v1/dashboards").status_code == 401
    assert remote.put("/v1/display-settings", json=DISPLAY).status_code == 401
