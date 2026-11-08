"""Smoke tests: the skeleton imports, serves /v1/health and the ports are satisfiable by fakes."""

import importlib
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from command_center.app import create_app
from command_center.core.ports import Clock, IdSource, Rng

LAYERS = [
    "core",
    "services",
    "adapters",
    "storage",
    "api",
    "web",
    "workers",
    "desktop",
    "pairing",
]


@pytest.mark.parametrize("layer", LAYERS)
def test_layer_package_imports(layer: str) -> None:
    assert importlib.import_module(f"command_center.{layer}") is not None


def test_health_endpoint_reports_ok() -> None:
    response = TestClient(create_app(), base_url="http://localhost").get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ports_accept_simple_fakes() -> None:
    class FixedClock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    class ZeroRng:
        def random(self) -> float:
            return 0.0

    class CountingIds:
        def new_id(self) -> str:
            return "id-1"

    clock: Clock = FixedClock()
    rng: Rng = ZeroRng()
    ids: IdSource = CountingIds()

    assert clock.now().year == 2026
    assert rng.random() == 0.0
    assert ids.new_id() == "id-1"


def test_the_worker_root_imports_without_running() -> None:
    # Import only: workers.__main__.main() is built now (decision 0070) and would parse sys.argv,
    # require CC_REDIS_URL and start a consumer loop.
    assert callable(importlib.import_module("command_center.workers.__main__").main)


def test_the_menu_bar_root_imports_without_running() -> None:
    # Import only: desktop.main.main() is built now and would start a server and the macOS menu bar.
    assert callable(importlib.import_module("command_center.desktop.main").main)
