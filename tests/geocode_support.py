"""Shared pieces for the city search tests: a fake Geocoder, canned places and an api rig."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from command_center.api import create_app
from command_center.core.geocode import GeocodeCandidate
from command_center.services.container import Container
from command_center.services.geocode import GeocodeService
from fakes import FakeClock
from web_rig import LOCAL, make_rig

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
TYPED_QUERY = "Zzyzx-fake-query"


def place(name: str = "Provo", region: str | None = "Utah", **fields: object) -> GeocodeCandidate:
    base: dict[str, object] = {
        "name": name,
        "region": region,
        "country": "United States",
        "latitude": 40.23384,
        "longitude": -111.65853,
        "population": 115_000,
    }
    return GeocodeCandidate.model_validate({**base, **fields})


class FakeGeocoder:
    """A Geocoder that returns canned places or raises a canned error; records the queries."""

    def __init__(self, outcome: list[GeocodeCandidate] | Exception | None = None) -> None:
        self.outcome = [place()] if outcome is None else outcome
        self.queries: list[str] = []

    async def search(self, query: str) -> list[GeocodeCandidate]:
        self.queries.append(query)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@dataclass
class GeocodeRig:
    client: TestClient
    container: Container
    geocoder: FakeGeocoder
    clock: FakeClock


def make_geocode_rig(
    outcome: list[GeocodeCandidate] | Exception | None = None, *, wired: bool = True
) -> GeocodeRig:
    web = make_rig(("canvas",))
    clock = FakeClock(NOW)
    geocoder = FakeGeocoder(outcome)
    service = GeocodeService(geocoder, clock) if wired else None
    container = replace(web.container, geocode=service)
    return GeocodeRig(TestClient(create_app(container), base_url=LOCAL), container, geocoder, clock)
