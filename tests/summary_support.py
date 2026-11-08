"""Shared wiring for the summary service and route tests."""

from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from builders import NOW
from command_center.core.summary import DailySummary
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.sync import SyncService
from fakes import (
    FakeClock,
    FakeSummaryProvider,
    InMemoryEventStore,
    InMemorySecretStore,
    InMemorySummaryStore,
)

TZ = ZoneInfo("America/Denver")
GOOD = DailySummary(headline="Busy day", priorities=["Essay"], heads_up=["Quiz Friday"])
OLD = DailySummary(headline="Yesterday's briefing")


@dataclass
class Rig:
    provider: FakeSummaryProvider
    events: InMemoryEventStore = field(default_factory=InMemoryEventStore)
    store: InMemorySummaryStore = field(default_factory=InMemorySummaryStore)
    include_email: bool = False

    @property
    def service(self) -> SummaryService:
        clock = FakeClock(NOW)
        return SummaryService(
            AgendaService(self.events, clock, TZ),
            self.store,
            self.provider,
            clock,
            TZ,
            include_email=self.include_email,
        )

    def container(self, summary: SummaryService | None) -> Container:
        clock = FakeClock(NOW)
        secrets = InMemorySecretStore()
        sync = SyncService({}, secrets, self.events, clock)
        return Container(
            sync=sync,
            agenda=AgendaService(self.events, clock, TZ),
            settings=SettingsService({}, secrets, sync),
            summary=summary,
        )
