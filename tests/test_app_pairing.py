"""The composition root wires pairing: a real device store, real tokens, the tailnet host."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from command_center.app import build_app, build_container
from command_center.config import Settings

TAILNET = "mac.tail1234.ts.net"


def make_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hosts: str = "") -> Settings:
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'pairing.db'}")
    monkeypatch.setenv("CC_ALLOWED_HOSTS", hosts)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_the_container_has_a_pairing_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    container = build_container(make_settings(monkeypatch, tmp_path))
    assert container.pairing is not None


def test_the_phone_url_is_https_on_the_first_listed_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = make_settings(monkeypatch, tmp_path, f"{TAILNET},other.ts.net")
    container = build_container(settings)
    assert container.pairing is not None
    assert container.pairing.base_url == f"https://{TAILNET}"


def test_without_a_listed_host_there_is_no_phone_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    container = build_container(make_settings(monkeypatch, tmp_path))
    assert container.pairing is not None
    assert container.pairing.base_url is None


def test_the_real_app_pairs_a_phone_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = build_app(make_settings(monkeypatch, tmp_path, TAILNET))
    with (
        TestClient(app, base_url="http://localhost") as local,
        TestClient(app, base_url=f"https://{TAILNET}") as remote,
    ):
        assert remote.get("/v1/settings").status_code == 401
        page = local.get("/settings").text
        csrf = page.split('"X-CSRF-Token": "')[1].split('"')[0]
        html = local.post("/pair/code", headers={"X-CSRF-Token": csrf}).text
        token = html.split('<code id="pair-token">')[1].split("</code>")[0]
        paired = remote.post(
            "/v1/pair", json={"pairing_token": token, "device_name": "Pixel"}
        ).json()
        headers = {"Authorization": f"Bearer {paired['access_token']}"}
        assert remote.get("/v1/settings", headers=headers).status_code == 200
        assert [d["name"] for d in local.get("/v1/devices").json()] == ["Pixel"]


def test_the_real_app_refuses_the_tailnet_name_when_none_is_listed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = build_app(make_settings(monkeypatch, tmp_path))
    with TestClient(app, base_url=f"https://{TAILNET}") as remote:
        assert remote.get("/v1/health").status_code == 400


def test_a_paired_phone_survives_a_restart(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = make_settings(monkeypatch, tmp_path, TAILNET)
    first = build_container(settings)
    assert first.pairing is not None
    issued = first.pairing.pair(first.pairing.start_pairing().token, "Pixel")
    second = build_container(settings)
    assert second.pairing is not None
    assert second.pairing.authenticate(issued.access_token) == issued.device_id
