"""The whole app through its real factory: API, web pages, static files and the Host check."""

import hashlib
from collections.abc import Iterator
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from builders import NOW, make_event
from command_center.api import create_app
from command_center.core.summary import DailySummary
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.sync import SyncService
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import (
    FakeClock,
    FakeSummaryProvider,
    InMemoryEventStore,
    InMemorySecretStore,
    InMemorySummaryStore,
)

DENVER = ZoneInfo("America/Denver")  # NOW is 05:00 on Sat 2026-11-07 there
DAY = "2026-11-07"
HTMX_SHA256 = "d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717"
CREDENTIALS = {"credentials": {"base_url": "https://school.example", "token": "fake-canvas-token"}}
SUMMARY = DailySummary(headline="A quiet Saturday", priorities=["Read chapter 3"], heads_up=[])


def build_container(*, summary: bool = False, connected: bool = False) -> Container:
    clock = FakeClock(NOW)
    secrets = InMemorySecretStore()
    if connected:
        secrets.set("canvas", "token", "fake-canvas-token")
    events = InMemoryEventStore()
    canvas = FakeAdapter(
        "canvas",
        script=[[make_event(id="essay", title="Essay draft", start=NOW + timedelta(hours=1))]],
    )
    adapters = {"canvas": canvas}
    sync = SyncService(adapters, secrets, events, clock, sleep=RecordingSleep())
    agenda = AgendaService(events, clock, DENVER)
    return Container(
        sync=sync,
        agenda=agenda,
        settings=SettingsService(adapters, secrets, sync),
        summary=SummaryService(
            agenda, InMemorySummaryStore(), FakeSummaryProvider(SUMMARY), clock, DENVER
        )
        if summary
        else None,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(build_container()), base_url="http://localhost") as found:
        yield found


def test_connecting_a_source_shows_syncing_then_ok(client: TestClient) -> None:
    connected = client.put("/v1/settings/canvas", json=CREDENTIALS).json()
    settled = client.get("/v1/settings").json()

    assert connected["ok"] is True
    assert connected["sync"]["status"] == "syncing"
    assert settled[0]["sync"]["status"] == "ok"


def test_a_synced_event_is_in_the_day_agenda(client: TestClient) -> None:
    client.put("/v1/settings/canvas", json=CREDENTIALS)

    titles = [item["title"] for item in client.get("/v1/agenda/day", params={"date": DAY}).json()]

    assert titles == ["Essay draft"]


def test_a_synced_event_is_on_the_rendered_today_page(client: TestClient) -> None:
    client.put("/v1/settings/canvas", json=CREDENTIALS)

    page = client.get("/", params={"date": DAY})

    assert page.status_code == 200
    assert "Essay draft" in page.text


def test_htmx_is_served_from_the_static_path_and_is_the_recorded_file(
    client: TestClient,
) -> None:
    response = client.get("/static/vendor/htmx.min.js")

    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == HTMX_SHA256


@pytest.mark.parametrize(
    "path", ["/", "/week", "/month", "/settings", "/static/vendor/htmx.min.js", "/v1/health"]
)
def test_the_host_check_rejects_another_host_on_every_surface(
    client: TestClient, path: str
) -> None:
    response = client.get(path, headers={"Host": "evil.example"})

    assert response.status_code == 400


def test_the_loopback_ip_is_a_served_host_for_the_web_pages(client: TestClient) -> None:
    assert client.get("/", headers={"Host": "127.0.0.1:8765"}).status_code == 200


def test_the_summary_route_says_summaries_are_off_by_default(client: TestClient) -> None:
    response = client.get("/v1/summary", params={"date": DAY})

    assert response.status_code == 404


def test_the_summary_appears_on_the_page_and_in_the_api_when_enabled() -> None:
    with TestClient(create_app(build_container(summary=True)), base_url="http://localhost") as c:
        c.put("/v1/settings/canvas", json=CREDENTIALS)

        api = c.get("/v1/summary", params={"date": DAY}).json()
        page = c.get("/", params={"date": DAY}).text

    assert api["summary"]["headline"] == "A quiet Saturday"
    assert "A quiet Saturday" in page


def test_the_page_shows_the_not_enabled_summary_card_while_summaries_are_off(
    client: TestClient,
) -> None:
    page = client.get("/", params={"date": DAY}).text

    assert "The AI summary is not enabled." in page
    assert "A quiet Saturday" not in page


def test_the_lifespan_syncs_connected_sources_without_any_request() -> None:
    app = create_app(build_container(connected=True), sync_interval_minutes=30)

    with TestClient(app, base_url="http://localhost") as client:
        # Each request yields to the event loop, so the startup sync gets its turns; no sleeping.
        states = client.get("/v1/settings").json()
        for _ in range(50):
            if states[0]["sync"] is not None:
                break
            states = client.get("/v1/settings").json()

    assert states[0]["sync"]["status"] == "ok"
