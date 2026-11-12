"""The /v1 dashboard and display-settings routes (decisions 0355 to 0358)."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from builders import NOW
from command_center.api import create_app
from command_center.services.dashboards import DashboardService
from command_center.storage.sqlite_dashboards import (
    create_dashboard_store,
    create_display_settings_store,
)
from dashboard_support import DISPLAY, SeqIds, dashboard_body, item, layout_doc
from fakes import FakeClock
from web_rig import make_rig


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    url = f"sqlite:///{tmp_path / 'cc.db'}"
    service = DashboardService(
        create_dashboard_store(url), create_display_settings_store(url), FakeClock(NOW), SeqIds()
    )
    container = replace(make_rig(("canvas",)).container, dashboards=service)
    return TestClient(create_app(container), base_url="http://localhost")


def _match(revision: int) -> dict[str, str]:
    return {"If-Match": f'"{revision}"'}


def test_the_routes_are_404_without_a_service() -> None:
    app = create_app(make_rig(("canvas",)).container)
    local = TestClient(app, base_url="http://localhost")
    assert local.get("/v1/dashboards").status_code == 404
    assert local.get("/v1/display-settings").status_code == 404


def test_create_then_list_and_get(client: TestClient) -> None:
    created = client.post("/v1/dashboards", json=dashboard_body())
    assert created.status_code == 201
    body = created.json()
    assert (body["id"], body["revision"], body["position"]) == ("d1", 1, 0)
    assert body["layout"] == layout_doc()  # the UI's own keys come back
    assert created.headers["etag"] == '"1"'
    assert created.headers["cache-control"] == "no-store"
    assert client.get("/v1/dashboards").json() == [body]
    got = client.get("/v1/dashboards/d1")
    assert got.json() == body
    assert got.headers["etag"] == '"1"'
    assert client.get("/v1/dashboards/nope").status_code == 404


def test_replace_with_the_current_revision_bumps_it(client: TestClient) -> None:
    client.post("/v1/dashboards", json=dashboard_body())
    saved = client.put("/v1/dashboards/d1", json=dashboard_body("Week"), headers=_match(1))
    assert saved.status_code == 200
    assert (saved.json()["name"], saved.json()["revision"]) == ("Week", 2)
    assert saved.headers["etag"] == '"2"'


def test_two_tabs_cannot_overwrite_each_other(client: TestClient) -> None:
    client.post("/v1/dashboards", json=dashboard_body())
    assert (
        client.put("/v1/dashboards/d1", json=dashboard_body("A"), headers=_match(1)).status_code
        == 200
    )
    stale = client.put("/v1/dashboards/d1", json=dashboard_body("B"), headers=_match(1))
    assert stale.status_code == 409
    assert client.get("/v1/dashboards/d1").json()["name"] == "A"
    assert client.delete("/v1/dashboards/d1", headers=_match(1)).status_code == 409
    assert client.get("/v1/dashboards/d1").status_code == 200


def test_a_write_without_if_match_is_428_and_a_bad_one_400(client: TestClient) -> None:
    client.post("/v1/dashboards", json=dashboard_body())
    assert client.put("/v1/dashboards/d1", json=dashboard_body()).status_code == 428
    assert client.delete("/v1/dashboards/d1").status_code == 428
    for bad in ('"abc"', "W/", "-1", '"1" "2"', ""):
        response = client.put("/v1/dashboards/d1", json=dashboard_body(), headers={"If-Match": bad})
        assert response.status_code == 400, bad


def test_delete_with_the_current_revision(client: TestClient) -> None:
    client.post("/v1/dashboards", json=dashboard_body())
    assert client.delete("/v1/dashboards/d1", headers=_match(1)).status_code == 204
    assert client.get("/v1/dashboards").json() == []
    assert client.delete("/v1/dashboards/d1", headers=_match(1)).status_code == 404


def test_reorder_and_a_stale_list(client: TestClient) -> None:
    for name in ("A", "B"):
        client.post("/v1/dashboards", json=dashboard_body(name))
    moved = client.put("/v1/dashboards/order", json={"ids": ["d2", "d1"]})
    assert [d["id"] for d in moved.json()] == ["d2", "d1"]
    assert [d["id"] for d in client.get("/v1/dashboards").json()] == ["d2", "d1"]
    assert client.put("/v1/dashboards/order", json={"ids": ["d1"]}).status_code == 409


def test_the_twenty_first_dashboard_is_409(client: TestClient) -> None:
    for _ in range(20):
        assert client.post("/v1/dashboards", json=dashboard_body()).status_code == 201
    assert client.post("/v1/dashboards", json=dashboard_body()).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "layout": {"version": 2, "items": []}},
        {"name": "x", "layout": layout_doc(item(widgetId="<b>"))},
        {"name": "x", "layout": layout_doc(item(extra=1))},
        {"name": "", "layout": layout_doc()},
        {"name": "x", "layout": layout_doc(), "extra": 1},
    ],
)
def test_an_invalid_dashboard_is_422_and_never_echoed(
    client: TestClient, body: dict[str, Any]
) -> None:
    response = client.post("/v1/dashboards", json=body)
    assert response.status_code == 422
    assert "<b>" not in response.text
    assert client.get("/v1/dashboards").json() == []


def test_an_oversized_item_list_is_422(client: TestClient) -> None:
    items = [item(id=f"w{i}") for i in range(51)]
    assert (
        client.post(
            "/v1/dashboards", json=dashboard_body(layout={"version": 1, "items": items})
        ).status_code
        == 422
    )


def test_display_settings_start_as_defaults_at_revision_zero(client: TestClient) -> None:
    response = client.get("/v1/display-settings")
    assert response.status_code == 200
    assert response.headers["etag"] == '"0"'
    assert (response.json()["revision"], response.json()["theme"]) == (0, "system")


def test_display_settings_save_and_conflict(client: TestClient) -> None:
    saved = client.put("/v1/display-settings", json=DISPLAY, headers=_match(0))
    assert saved.status_code == 200
    assert (saved.json()["revision"], saved.json()["glow"]) == (1, 1.6)
    assert client.get("/v1/display-settings").json()["source_colors"] == DISPLAY["source_colors"]
    assert client.put("/v1/display-settings", json=DISPLAY, headers=_match(0)).status_code == 409
    assert client.put("/v1/display-settings", json=DISPLAY).status_code == 428


@pytest.mark.parametrize(
    "change",
    [
        {"text_scale": 200},
        {"glow": 2},
        {"theme": "x"},
        {"api_key": "fake-key-123"},
        {"provider": "gemini"},
    ],
)
def test_invalid_display_settings_are_422_and_store_nothing(
    client: TestClient, change: dict[str, Any]
) -> None:
    response = client.put("/v1/display-settings", json={**DISPLAY, **change}, headers=_match(0))
    assert response.status_code == 422
    assert "fake-key" not in response.text
    assert client.get("/v1/display-settings").json()["revision"] == 0


def test_writes_keep_the_json_and_cross_site_rules(client: TestClient) -> None:
    form = client.post("/v1/dashboards", data={"name": "x"})
    assert form.status_code == 415
    cross = client.post(
        "/v1/dashboards", json=dashboard_body(), headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert cross.status_code == 403
    other = client.put(
        "/v1/display-settings",
        json=DISPLAY,
        headers={**_match(0), "Origin": "https://evil.example"},
    )
    assert other.status_code == 403
    assert client.get("/v1/dashboards").json() == []


def test_a_malformed_dashboard_id_is_422(client: TestClient) -> None:
    assert client.get("/v1/dashboards/has space").status_code == 422
    assert client.get("/v1/dashboards/" + "x" * 65).status_code == 422
