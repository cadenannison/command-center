"""A web app whose container has a SummaryControl over in-memory stores and a counting provider."""

from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.testclient import TestClient

from builders import NOW, make_event
from command_center.core.summary import DailySummary
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.summary_control import SummaryControl
from command_center.services.sync import SyncService
from command_center.web import create_router
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import (
    FakeClock,
    FakeSummaryProvider,
    InMemoryAppSettingStore,
    InMemoryEventStore,
    InMemorySecretStore,
    InMemorySummaryStore,
)
from web_rig import CSRF, DENVER, LOCAL

GOOD = DailySummary(headline="Busy Saturday", priorities=["Finish essay"], heads_up=["Quiz Monday"])
KEY = "fake-gemini-key-ABCD1234"


@dataclass
class CardRig:
    client: TestClient
    container: Container
    control: SummaryControl
    provider: FakeSummaryProvider
    settings_store: InMemoryAppSettingStore
    secrets: InMemorySecretStore
    summaries: InMemorySummaryStore
    built: list[str] = field(default_factory=list[str])

    @property
    def headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": CSRF}

    def post(self, path: str, data: dict[str, str] | None = None) -> str:
        response = self.client.post(path, data=data or {}, headers=self.headers)
        assert response.status_code == 200, response.text
        return response.text


def make_card_rig(
    outcome: DailySummary | Exception = GOOD,
    *,
    enabled: bool = False,
    provider: str = "gemini",
    key: bool = True,
    with_control: bool = True,
) -> CardRig:
    secrets = InMemorySecretStore()
    if key:
        secrets.set("gemini", "api_key", KEY)
    events = InMemoryEventStore()
    events.upsert([make_event(id="x", start=NOW)])
    clock = FakeClock(NOW)
    sync = SyncService({}, secrets, events, clock, sleep=RecordingSleep())
    agenda = AgendaService(events, clock, DENVER)
    fake = FakeSummaryProvider(outcome)
    built: list[str] = []
    summaries = InMemorySummaryStore()

    def build(name: str) -> SummaryService:
        built.append(name)
        return SummaryService(agenda, summaries, fake, clock, DENVER)

    store = InMemoryAppSettingStore()
    control = SummaryControl(
        store,
        build,
        default_enabled=enabled,
        default_provider=provider,
        forget_today=lambda: summaries.delete(agenda.today()),
    )
    container = Container(
        sync=sync,
        agenda=agenda,
        settings=SettingsService({}, secrets, sync, {"gemini": FakeAdapter("gemini")}),
        summary_control=control if with_control else None,
    )
    app = FastAPI()
    app.include_router(create_router(container, csrf_token=CSRF))
    return CardRig(
        TestClient(app, base_url=LOCAL), container, control, fake, store, secrets, summaries, built
    )
