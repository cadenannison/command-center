"""Composition root for the API process: wires concrete infrastructure."""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from command_center.adapters.json_log import configure_json_logging
from command_center.adapters.queue_redis import RedisStreamsQueue, source_queue_prefix
from command_center.adapters.secret_backend import build_secret_store
from command_center.adapters.source_registry import build_source_adapters
from command_center.adapters.summary_gemini import GeminiIntegration, GeminiSummaryProvider
from command_center.adapters.summary_ollama import OllamaSummaryProvider
from command_center.adapters.system_clock import SystemClock
from command_center.adapters.system_ids import UuidIdSource
from command_center.adapters.system_rng import SystemRng
from command_center.adapters.system_tokens import SystemTokenSource
from command_center.api import create_app as create_api_app
from command_center.config import Settings
from command_center.core.ports import (
    Clock,
    EventStore,
    IntegrationAdapter,
    SecretStore,
    SourceAdapter,
    SummaryProvider,
    SyncStateStore,
)
from command_center.core.resilience import DEFAULT_RETRY_POLICY
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.pairing import PairingService
from command_center.services.queued_sync import QueuedSyncService
from command_center.services.scheduler import SyncEnqueuer
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.sync import SyncService
from command_center.storage.sqlite import create_event_store
from command_center.storage.sqlite_devices import create_device_store
from command_center.storage.sqlite_generations import create_generation_store
from command_center.storage.sqlite_states import create_sync_state_store
from command_center.storage.sqlite_summary import create_summary_store

if TYPE_CHECKING:
    from command_center.services.sync_control import SyncControl


def build_adapters(tz: ZoneInfo, clock: Clock) -> dict[str, SourceAdapter]:
    """The five sources, keyed by the name each reports (shared with the workers' root)."""
    return build_source_adapters(tz, clock)


def build_integrations(settings: Settings) -> dict[str, IntegrationAdapter]:
    """The credential-only integrations: the Gemini key, checked with Gemini's model name."""
    # summary_model names the chosen provider's model; an Ollama name is not a Gemini model.
    if settings.summary_provider == "gemini" and settings.summary_model is not None:
        gemini = GeminiIntegration(model=settings.summary_model)
    else:
        gemini = GeminiIntegration()
    return {gemini.name: gemini}


def build_summary_provider(settings: Settings, secrets: SecretStore) -> SummaryProvider:
    """The configured provider. Gemini reads its key from the secret store on every call."""
    if settings.summary_provider == "ollama":
        if settings.summary_model is None:
            return OllamaSummaryProvider()
        return OllamaSummaryProvider(model=settings.summary_model)
    if settings.summary_model is None:
        return GeminiSummaryProvider(secrets)
    return GeminiSummaryProvider(secrets, model=settings.summary_model)


def build_pairing(settings: Settings, clock: Clock) -> PairingService:
    """Phone pairing over the same database. The phone's URL is https on the first allowed host.

    Tailscale Serve answers HTTPS on 443 for the tailnet name, so no port is added; with no
    allowed host there is no URL and the /pair page says how to set one.
    """
    base_url = f"https://{settings.allowed_hosts[0]}" if settings.allowed_hosts else None
    return PairingService(
        create_device_store(settings.database_url), SystemTokenSource(), clock, base_url=base_url
    )


def build_queued_sync(  # noqa: PLR0913, PLR0917
    settings: Settings,
    sources: list[str],
    secrets: SecretStore,
    events: EventStore,
    states: SyncStateStore,
    clock: Clock,
) -> tuple[QueuedSyncService, Callable[[], Awaitable[None]]]:
    """The distributed api's sync: one Redis queue per source, and a function that closes them.

    Nothing fetches in the api: a sync is a job for the source's worker (decision 0074).
    """
    if not settings.redis_url:
        msg = "CC_REDIS_URL is not set: distributed mode talks to Redis"
        raise ValueError(msg)
    generations = create_generation_store(settings.database_url)
    queues = {
        source: RedisStreamsQueue.from_url(
            settings.redis_url,
            clock,
            SystemRng(),
            prefix=source_queue_prefix(source),
            policy=DEFAULT_RETRY_POLICY,
        )
        for source in sources
    }
    enqueuer = SyncEnqueuer(
        sources, secrets, queues, clock, UuidIdSource(), generations=generations
    )

    async def close() -> None:
        for queue in queues.values():
            await queue.aclose()
        generations.close()

    return QueuedSyncService(sources, enqueuer, states, events, generations, clock), close


def build_container(settings: Settings | None = None) -> Container:
    """Build the real services: SQLite or Postgres storage, keychain or file secrets, the clock.

    `container.summary` stays None unless `summary_enabled`: with the default no provider is
    built, so nothing can be sent anywhere (decision 0004).
    """
    settings = settings or Settings()
    tz = ZoneInfo(settings.tz)
    clock = SystemClock()
    secrets = build_secret_store(settings.secret_backend, settings.data_dir)
    events = create_event_store(settings.database_url)
    states = create_sync_state_store(settings.database_url)
    adapters = build_adapters(tz, clock)
    sync: SyncControl
    close: Callable[[], Awaitable[None]] | None = None
    if settings.mode == "distributed":
        sync, close = build_queued_sync(settings, list(adapters), secrets, events, states, clock)
    else:
        sync = SyncService(adapters, secrets, events, clock, states=states)
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
        settings=SettingsService(adapters, secrets, sync, build_integrations(settings)),
        summary=summary,
        pairing=build_pairing(settings, clock),
        close=close,
    )


def build_app(settings: Settings) -> FastAPI:
    """The app for these settings; the container is built when the server starts, not here.

    In distributed mode the API schedules nothing: the scheduler process enqueues the syncs.
    """
    distributed = settings.mode == "distributed"
    return create_api_app(
        lambda: build_container(settings),
        sync_interval_minutes=None if distributed else settings.sync_interval_minutes,
        remote_hosts=settings.allowed_hosts,
    )


def create_app() -> FastAPI:
    """The production app; its container is built at startup, not at import or construction."""
    return build_app(Settings())


def main() -> None:  # pragma: no cover - process entry point
    """Run the API and web UI: loopback, or 0.0.0.0 only with CC_BIND_ALL (decision 0072)."""
    import uvicorn  # noqa: PLC0415

    settings = Settings()
    configure_json_logging()
    # log_config=None leaves uvicorn's loggers to propagate to the JSON handler.
    uvicorn.run(build_app(settings), host=settings.listen_host, port=settings.port, log_config=None)
