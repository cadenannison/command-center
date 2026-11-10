"""The composition root wires city search with the real adapter and the system clock."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import respx

from command_center.adapters.weather_geocode import URL
from command_center.app import build_container
from command_center.config import Settings
from command_center.services.geocode import GeocodeService


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'geocode.db'}")
    monkeypatch.setenv("CC_TZ", "America/Denver")
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def test_the_real_container_has_a_city_search(settings: Settings) -> None:
    container = build_container(settings)

    assert isinstance(container.geocode, GeocodeService)


async def test_the_city_search_asks_open_meteo(
    settings: Settings, router: respx.MockRouter
) -> None:
    route = router.get(URL).respond(
        json={"results": [{"name": "Provo", "latitude": 40.2, "longitude": -111.6}]}
    )
    service = build_container(settings).geocode
    assert service is not None

    found = await service.search("Provo")

    assert [item.name for item in found] == ["Provo"]
    assert route.call_count == 1
