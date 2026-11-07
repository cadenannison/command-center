"""The composition root: the real container, and a lazy production app."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from command_center.api import create_app as create_api_app
from command_center.app import build_container, create_app
from command_center.config import Settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'wiring.db'}")
    monkeypatch.setenv("CC_TZ", "America/Denver")
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_build_container_wires_real_storage_with_no_sources_registered(settings: Settings) -> None:
    container = build_container(settings)

    assert container.sync.sources() == []


def test_the_real_container_serves_an_empty_agenda_and_settings(settings: Settings) -> None:
    app = create_api_app(lambda: build_container(settings))

    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/v1/agenda/day", params={"date": "2026-11-07"}).json() == []
        assert client.get("/v1/settings").json() == []
        assert client.post("/v1/sync").json() == []


def test_the_production_app_builds_nothing_until_it_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_DATABASE_URL", "sqlite:////nonexistent-root/never/created.db")

    app = create_app()

    assert not hasattr(app.state, "container")
    assert "/v1/settings/{source}" in app.openapi()["paths"]
