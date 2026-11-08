"""Composition root for the API process: wires concrete infrastructure."""

from zoneinfo import ZoneInfo

from fastapi import FastAPI

from command_center.adapters.caldav_apple import AppleCalendarAdapter
from command_center.adapters.canvas import CanvasAdapter
from command_center.adapters.gmail import GmailAdapter
from command_center.adapters.ical_feed import IcalFeedAdapter
from command_center.adapters.keyring_store import KeyringSecretStore
from command_center.adapters.summary_gemini import GeminiSummaryProvider
from command_center.adapters.summary_ollama import OllamaSummaryProvider
from command_center.adapters.system_clock import SystemClock
from command_center.adapters.weather import WeatherAdapter
from command_center.api import create_app as create_api_app
from command_center.config import Settings
from command_center.core.ports import Clock, SecretStore, SourceAdapter, SummaryProvider
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.sync import SyncService
from command_center.storage.sqlite import create_event_store
from command_center.storage.sqlite_summary import create_summary_store


def build_adapters(tz: ZoneInfo, clock: Clock) -> dict[str, SourceAdapter]:
    """The five sources, keyed by the name each reports."""
    adapters: list[SourceAdapter] = [
        CanvasAdapter(clock),
        AppleCalendarAdapter(tz, clock),
        IcalFeedAdapter(tz, clock),
        GmailAdapter(clock),
        WeatherAdapter(clock),
    ]
    return {adapter.name: adapter for adapter in adapters}


def build_summary_provider(settings: Settings, secrets: SecretStore) -> SummaryProvider:
    """The configured provider. Gemini reads its key from the secret store on every call."""
    if settings.summary_provider == "ollama":
        if settings.summary_model is None:
            return OllamaSummaryProvider()
        return OllamaSummaryProvider(model=settings.summary_model)
    if settings.summary_model is None:
        return GeminiSummaryProvider(secrets)
    return GeminiSummaryProvider(secrets, model=settings.summary_model)


def build_container(settings: Settings | None = None) -> Container:
    """Build the real services: SQLite or Postgres storage, keychain secrets, the system clock.

    `container.summary` stays None unless `summary_enabled`: with the default no provider is
    built, so nothing can be sent anywhere (decision 0004).
    """
    settings = settings or Settings()
    tz = ZoneInfo(settings.tz)
    clock = SystemClock()
    secrets = KeyringSecretStore()
    events = create_event_store(settings.database_url)
    adapters = build_adapters(tz, clock)
    sync = SyncService(adapters, secrets, events, clock)
    agenda = AgendaService(events, clock, tz)
    summary: SummaryService | None = None
    if settings.summary_enabled:
        summary = SummaryService(
            agenda,
            create_summary_store(settings.database_url),
            build_summary_provider(settings, secrets),
            clock,
            tz,
            include_email=settings.summary_include_email,
        )
    return Container(
        sync=sync,
        agenda=agenda,
        settings=SettingsService(adapters, secrets, sync),
        summary=summary,
    )


def build_app(settings: Settings) -> FastAPI:
    """The app for these settings; the container is built when the server starts, not here."""
    return create_api_app(
        lambda: build_container(settings), sync_interval_minutes=settings.sync_interval_minutes
    )


def create_app() -> FastAPI:
    """The production app; its container is built at startup, not at import or construction."""
    return build_app(Settings())


def main() -> None:  # pragma: no cover - process entry point
    """Run the API and web UI on the configured host, which Settings restricts to loopback."""
    import uvicorn  # noqa: PLC0415

    settings = Settings()
    uvicorn.run(build_app(settings), host=settings.host, port=settings.port)
