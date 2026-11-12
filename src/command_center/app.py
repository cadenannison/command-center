"""Composition root for the API process: wires concrete infrastructure."""

import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC
from typing import TYPE_CHECKING, TextIO
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from command_center.adapters.chat_ollama import DEFAULT_BASE_URL as OLLAMA_CHAT_URL
from command_center.adapters.chat_ollama import DEFAULT_MODEL as OLLAMA_CHAT_MODEL
from command_center.adapters.chat_ollama import OllamaChatProvider
from command_center.adapters.chat_openai import ChatKeyIntegration, OpenAICompatibleChatProvider
from command_center.adapters.ical_diagnose import diagnose_feeds
from command_center.adapters.ical_diagnose_report import render
from command_center.adapters.ical_feed import SOURCE_NAME as LEARNINGSUITE
from command_center.adapters.ical_feed import feed_urls
from command_center.adapters.json_log import configure_json_logging
from command_center.adapters.log_redaction import install_query_redaction
from command_center.adapters.queue_redis import RedisStreamsQueue, source_queue_prefix
from command_center.adapters.secret_backend import build_secret_store
from command_center.adapters.source_registry import build_source_adapters
from command_center.adapters.summary_gemini import (
    DEFAULT_MODEL as GEMINI_MODEL,
)
from command_center.adapters.summary_gemini import (
    GeminiChatProvider,
    GeminiIntegration,
    GeminiSummaryProvider,
)
from command_center.adapters.summary_ollama import OllamaSummaryProvider
from command_center.adapters.system_clock import SystemClock
from command_center.adapters.system_ids import UuidIdSource
from command_center.adapters.system_rng import SystemRng
from command_center.adapters.system_tokens import SystemTokenSource
from command_center.adapters.weather_geocode import OpenMeteoGeocoder
from command_center.api import create_app as create_api_app
from command_center.config import Settings
from command_center.core.errors import SecretStoreError
from command_center.core.ports import (
    ChatProvider,
    Clock,
    EventStore,
    IntegrationAdapter,
    ItemLedger,
    SecretStore,
    SourceAdapter,
    SummaryProvider,
    SyncStateStore,
)
from command_center.core.resilience import DEFAULT_RETRY_POLICY
from command_center.services.agenda import AgendaService
from command_center.services.chat import ChatService
from command_center.services.chat_settings import ChatConfig, ChatDefaults, ChatSettings
from command_center.services.container import Container
from command_center.services.dashboards import DashboardService
from command_center.services.geocode import GeocodeService
from command_center.services.horizon import horizon_window
from command_center.services.items import ItemService
from command_center.services.pairing import PairingService
from command_center.services.queued_sync import QueuedSyncService
from command_center.services.scheduler import SyncEnqueuer
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.summary_control import SummaryControl
from command_center.services.sync import SyncService
from command_center.storage.sqlite import create_event_store
from command_center.storage.sqlite_app_settings import create_app_setting_store
from command_center.storage.sqlite_dashboards import (
    create_dashboard_store,
    create_display_settings_store,
)
from command_center.storage.sqlite_devices import create_device_store
from command_center.storage.sqlite_generations import create_generation_store
from command_center.storage.sqlite_items import create_item_ledger
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
    integrations: dict[str, IntegrationAdapter] = {gemini.name: gemini}
    chat_key = ChatKeyIntegration()
    integrations[chat_key.name] = chat_key
    return integrations


def build_chat_provider(secrets: SecretStore, config: ChatConfig) -> ChatProvider:
    """The chat provider for a validated config. Keys are read from `secrets` on every call."""
    if config.kind == "ollama":
        return OllamaChatProvider(
            base_url=config.base_url or OLLAMA_CHAT_URL, model=config.model or OLLAMA_CHAT_MODEL
        )
    if config.kind == "openai_compatible":
        # ChatSettings refuses an OpenAI-compatible config without an address and a model.
        return OpenAICompatibleChatProvider(
            secrets, base_url=config.base_url or "", model=config.model or ""
        )
    return GeminiChatProvider(secrets, model=config.model or GEMINI_MODEL)


def build_summary_provider(
    settings: Settings, secrets: SecretStore, provider: str | None = None
) -> SummaryProvider:
    """The named provider (default: the configured one). Gemini reads its key on every call.

    `summary_model` names a model of the configured provider only; another provider uses its own.
    """
    chosen = provider or settings.summary_provider
    model = settings.summary_model if chosen == settings.summary_provider else None
    if chosen == "ollama":
        return OllamaSummaryProvider() if model is None else OllamaSummaryProvider(model=model)
    return (
        GeminiSummaryProvider(secrets)
        if model is None
        else GeminiSummaryProvider(secrets, model=model)
    )


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
    ledger: ItemLedger | None = None,
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

    return (
        QueuedSyncService(sources, enqueuer, states, events, generations, clock, ledger=ledger),
        close,
    )


def build_container(settings: Settings | None = None) -> Container:
    """Build the real services: SQLite or Postgres storage, keychain or file secrets, the clock.

    `container.summary` stays None unless the environment's `summary_enabled` is set: with the
    default no provider is built at startup. The stored switch (`summary_control`) can turn
    summaries on later, and `container.summary_service()` is what the api and web call, so a
    summary that is off sends nothing anywhere (decisions 0004, 0112).
    """
    settings = settings or Settings()
    tz = ZoneInfo(settings.tz)
    clock = SystemClock()
    secrets = build_secret_store(settings.secret_backend, settings.data_dir)
    events = create_event_store(settings.database_url, clock)
    ledger = create_item_ledger(settings.database_url)
    states = create_sync_state_store(settings.database_url)
    adapters = build_adapters(tz, clock)
    sync: SyncControl
    close: Callable[[], Awaitable[None]] | None = None
    if settings.mode == "distributed":
        sync, close = build_queued_sync(
            settings, list(adapters), secrets, events, states, clock, ledger
        )
    else:
        sync = SyncService(adapters, secrets, events, clock, states=states, ledger=ledger)
    agenda = AgendaService(events, clock, tz, ledger)
    summary_store = create_summary_store(settings.database_url)

    def build_service(provider: str) -> SummaryService:
        return SummaryService(
            agenda,
            summary_store,
            build_summary_provider(settings, secrets, provider),
            clock,
            tz,
            include_email=settings.summary_include_email,
        )

    summary = build_service(settings.summary_provider) if settings.summary_enabled else None
    control = SummaryControl(
        create_app_setting_store(settings.database_url),
        lambda provider: (
            summary
            if summary is not None and provider == settings.summary_provider
            else build_service(provider)
        ),
        default_enabled=settings.summary_enabled,
        default_provider=settings.summary_provider,
        forget_today=lambda: summary_store.delete(agenda.today()),
    )
    items = ItemService(ledger, agenda, clock, UuidIdSource())
    chat = ChatService(
        ChatSettings(
            create_app_setting_store(settings.database_url),
            ChatDefaults(
                enabled=settings.chat_enabled,
                kind=settings.chat_provider,
                base_url=settings.chat_base_url,
                model=settings.chat_model,
            ),
        ),
        agenda,
        items,
        lambda config: build_chat_provider(secrets, config),
        clock,
        UuidIdSource(),
    )
    return Container(
        sync=sync,
        agenda=agenda,
        settings=SettingsService(adapters, secrets, sync, build_integrations(settings), clock),
        summary=summary,
        summary_control=control,
        pairing=build_pairing(settings, clock),
        close=close,
        geocode=GeocodeService(OpenMeteoGeocoder(), clock),
        items=items,
        chat=chat,
        dashboards=DashboardService(
            create_dashboard_store(settings.database_url),
            create_display_settings_store(settings.database_url),
            clock,
            UuidIdSource(),
        ),
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


USAGE = "usage: command-center [diagnose learningsuite]"


def diagnose_learningsuite(settings: Settings, out: TextIO, clock: Clock | None = None) -> int:
    """Print counts and categories for the stored LearningSuite feeds; exit code 0 or 1.

    The URLs come from the normal secret store and go nowhere but the feed requests. The window is
    the sync's own (UTC midnights, as in SyncService), so "inside the window" matches a sync.
    """
    try:
        creds = build_secret_store(settings.secret_backend, settings.data_dir).get(LEARNINGSUITE)
    except SecretStoreError:
        out.write("secret store unavailable\n")
        return 1
    urls = feed_urls(creds)
    window = horizon_window((clock or SystemClock()).now().astimezone(UTC))
    reports = asyncio.run(diagnose_feeds(urls, ZoneInfo(settings.tz), window))
    out.write(render(reports, window) + "\n")
    return 0


def run_command(
    argv: Sequence[str], settings: Settings, out: TextIO, err: TextIO, clock: Clock | None = None
) -> int:
    """Run a subcommand other than serving; 2 for one we do not know."""
    if list(argv) == ["diagnose", LEARNINGSUITE]:
        return diagnose_learningsuite(settings, out, clock)
    err.write(USAGE + "\n")
    return 2


def main() -> None:  # pragma: no cover - process entry point
    """Run the API and web UI: loopback, or 0.0.0.0 only with CC_BIND_ALL (decision 0072).

    With arguments it runs a subcommand instead (`diagnose learningsuite`) and exits.
    """
    if len(sys.argv) > 1:
        sys.exit(run_command(sys.argv[1:], Settings(), sys.stdout, sys.stderr))
    import uvicorn  # noqa: PLC0415

    settings = Settings()
    configure_json_logging()
    install_query_redaction()  # the city search text is typed by the user; keep it out of the log
    # log_config=None leaves uvicorn's loggers to propagate to the JSON handler.
    uvicorn.run(build_app(settings), host=settings.listen_host, port=settings.port, log_config=None)
