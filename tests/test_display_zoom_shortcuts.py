"""The `zoom` and `shortcuts` display settings (decision 0389): bounds, defaults, old shapes."""

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from builders import NOW
from command_center.api import create_app
from command_center.core.dashboards import DisplayInput
from command_center.services.dashboards import DashboardService
from command_center.storage.sqlite_dashboards import (
    SqliteDashboardStore,
    SqliteDisplaySettingsStore,
    ensure_dashboard_schema,
)
from dashboard_support import DISPLAY, SeqIds
from fakes import FakeClock
from sink_support import DATABASES, open_engine
from web_rig import make_rig

OLD_KEYS = [
    "theme",
    "high_contrast",
    "density",
    "glow",
    "text_scale",
    "privacy_mode",
    "source_colors",
    "owed_replies_as_tasks",
]
OLD_SHAPE: dict[str, Any] = {k: DISPLAY[k] for k in OLD_KEYS}


@pytest.fixture(params=DATABASES)
def rig(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[tuple[TestClient, Any]]:
    for engine in open_engine(request.param, tmp_path):
        ensure_dashboard_schema(engine)
        service = DashboardService(
            SqliteDashboardStore(engine),
            SqliteDisplaySettingsStore(engine),
            FakeClock(NOW),
            SeqIds(),
        )
        container = replace(make_rig(("canvas",)).container, dashboards=service)
        yield TestClient(create_app(container), base_url="http://localhost"), engine


def _match(revision: int) -> dict[str, str]:
    return {"If-Match": f'"{revision}"'}


def test_the_new_keys_default_when_absent() -> None:
    d = DisplayInput.model_validate(OLD_SHAPE)
    assert (d.zoom, d.shortcuts) == (100, True)
    assert (DisplayInput().zoom, DisplayInput().shortcuts) == (100, True)


@pytest.mark.parametrize("zoom", [70, 100, 130])
def test_zoom_edges_are_accepted(zoom: int) -> None:
    assert DisplayInput.model_validate({**DISPLAY, "zoom": zoom}).zoom == zoom


@pytest.mark.parametrize("shortcuts", [True, False])
def test_shortcuts_accepts_a_boolean(*, shortcuts: bool) -> None:
    assert DisplayInput.model_validate({**DISPLAY, "shortcuts": shortcuts}).shortcuts is shortcuts


@pytest.mark.parametrize(
    "change",
    [
        {"zoom": 69},
        {"zoom": 131},
        {"zoom": 0},
        {"zoom": -100},
        {"zoom": 100.5},
        {"zoom": 100.0},
        {"zoom": "100"},
        {"zoom": True},
        {"zoom": None},
        {"shortcuts": "yes"},
        {"shortcuts": 1},
        {"shortcuts": None},
        {"zooms": 100},
    ],
)
def test_a_bad_new_key_is_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DisplayInput.model_validate({**DISPLAY, **change})


@pytest.mark.parametrize("change", [{"zoom": 987654}, {"zoom": "fake-zoom-777"}])
def test_the_error_does_not_echo_the_value(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as caught:
        DisplayInput.model_validate({**DISPLAY, **change})
    assert "987654" not in str(caught.value)
    assert "fake-zoom-777" not in str(caught.value)


def test_unknown_keys_are_still_refused() -> None:
    with pytest.raises(ValidationError):
        DisplayInput.model_validate({**DISPLAY, "api_key": "fake-key-1"})


def test_a_round_trip_through_the_api(rig: tuple[TestClient, Any]) -> None:
    client, _ = rig
    body = {**DISPLAY, "zoom": 85, "shortcuts": False}
    saved = client.put("/v1/display-settings", json=body, headers=_match(0))
    assert saved.status_code == 200
    assert (saved.json()["zoom"], saved.json()["shortcuts"]) == (85, False)
    got = client.get("/v1/display-settings").json()
    assert (got["zoom"], got["shortcuts"], got["revision"]) == (85, False, 1)


def test_the_defaults_are_served_before_any_save(rig: tuple[TestClient, Any]) -> None:
    client, _ = rig
    got = client.get("/v1/display-settings").json()
    assert (got["zoom"], got["shortcuts"], got["revision"]) == (100, True, 0)


def test_an_old_shape_put_still_works_and_stores_defaults(rig: tuple[TestClient, Any]) -> None:
    client, _ = rig
    saved = client.put("/v1/display-settings", json=OLD_SHAPE, headers=_match(0))
    assert saved.status_code == 200
    assert (saved.json()["zoom"], saved.json()["shortcuts"]) == (100, True)
    assert client.get("/v1/display-settings").json()["theme"] == "dark"


def test_an_old_stored_document_reads_back_with_defaults(rig: tuple[TestClient, Any]) -> None:
    client, engine = rig
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO display_settings (user_id, settings, revision, updated_at) "
                "VALUES ('local', :s, 3, :t)"
            ),
            {"s": json.dumps(OLD_SHAPE), "t": NOW.strftime("%Y-%m-%dT%H:%M:%S.%fZ")},
        )
    got = client.get("/v1/display-settings").json()
    assert (got["theme"], got["zoom"], got["shortcuts"], got["revision"]) == ("dark", 100, True, 3)
    assert (
        client.put("/v1/display-settings", json=DISPLAY, headers=_match(3)).json()["revision"] == 4
    )


def test_a_bad_new_value_is_422_and_stores_nothing(rig: tuple[TestClient, Any]) -> None:
    client, _ = rig
    for change in ({"zoom": 131}, {"zoom": "fake-zoom-777"}, {"shortcuts": "fake-yes-777"}):
        response = client.put("/v1/display-settings", json={**DISPLAY, **change}, headers=_match(0))
        assert response.status_code == 422
        assert "fake-zoom-777" not in response.text
        assert "fake-yes-777" not in response.text
    assert client.get("/v1/display-settings").json()["revision"] == 0


def test_if_match_behaves_as_before(rig: tuple[TestClient, Any]) -> None:
    client, _ = rig
    body = {**DISPLAY, "zoom": 120}
    assert client.put("/v1/display-settings", json=body, headers=_match(0)).status_code == 200
    assert client.put("/v1/display-settings", json=body, headers=_match(0)).status_code == 409
    assert client.put("/v1/display-settings", json=body).status_code == 428
    assert (
        client.put("/v1/display-settings", json=body, headers={"If-Match": "x"}).status_code == 400
    )
    assert client.put("/v1/display-settings", json=body, headers=_match(1)).status_code == 200


def test_the_422_has_the_same_shape_as_an_old_key(rig: tuple[TestClient, Any]) -> None:
    client, _ = rig
    old = client.put("/v1/display-settings", json={**DISPLAY, "text_scale": 200}, headers=_match(0))
    new = client.put("/v1/display-settings", json={**DISPLAY, "zoom": 200}, headers=_match(0))
    assert (old.status_code, new.status_code) == (422, 422)
    assert old.json().keys() == new.json().keys()
