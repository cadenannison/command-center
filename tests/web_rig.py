"""A FastAPI app with only the web router, over fake adapters and in-memory stores."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from builders import NOW
from command_center.core.schema import Event
from command_center.core.summary import DailySummary
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.sync import SyncService
from command_center.web import create_router
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import (
    FakeClock,
    FakeSummaryProvider,
    InMemoryEventStore,
    InMemorySecretStore,
    InMemorySummaryStore,
)

DENVER = ZoneInfo("America/Denver")  # UTC-7 in November: NOW is 05:00 on Sat 2026-11-07
CSRF = "fake-csrf-token-for-tests"
LOCAL = "http://localhost"


@dataclass
class WebRig:
    client: TestClient
    app: FastAPI
    container: Container
    adapters: dict[str, FakeAdapter]
    secrets: InMemorySecretStore
    events: InMemoryEventStore
    clock: FakeClock

    @property
    def headers(self) -> dict[str, str]:
        """What the page's htmx would add to every request."""
        return {"X-CSRF-Token": CSRF}

    def seed(self, *events: Event) -> None:
        self.events.upsert(list(events))


def make_rig(
    sources: Sequence[str] = ("canvas",),
    *,
    summary: DailySummary | Exception | None = None,
    adapters: dict[str, FakeAdapter] | None = None,
    secrets: InMemorySecretStore | None = None,
) -> WebRig:
    secrets = secrets or InMemorySecretStore()
    events = InMemoryEventStore()
    clock = FakeClock(NOW)
    registered = adapters or {name: FakeAdapter(name) for name in sources}
    sync = SyncService(registered, secrets, events, clock, sleep=RecordingSleep())
    agenda = AgendaService(events, clock, DENVER)
    container = Container(
        sync=sync,
        agenda=agenda,
        settings=SettingsService(registered, secrets, sync),
        summary=None
        if summary is None
        else SummaryService(
            agenda, InMemorySummaryStore(), FakeSummaryProvider(summary), clock, DENVER
        ),
    )
    app = FastAPI()
    app.include_router(create_router(container, csrf_token=CSRF))
    client = TestClient(app, base_url=LOCAL)
    return WebRig(client, app, container, registered, secrets, events, clock)


def section(html: str, heading_id: str) -> str:
    """The <section> whose aria-labelledby is heading_id."""
    match = re.search(
        rf'<section[^>]*aria-labelledby="{heading_id}".*?</section>', html, flags=re.DOTALL
    )
    assert match is not None, f"no section {heading_id} in the page"
    return match.group(0)
