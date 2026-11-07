"""Composition root for the API process: wires concrete infrastructure."""

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from command_center.adapters.keyring_store import KeyringSecretStore
from command_center.adapters.system_clock import SystemClock
from command_center.api import create_app as create_api_app
from command_center.config import Settings
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from command_center.storage.sqlite import create_event_store

if TYPE_CHECKING:
    from command_center.core.ports import SourceAdapter


def build_container(settings: Settings | None = None) -> Container:
    """Build the real services: SQLite or Postgres events, keychain secrets, the system clock.

    No source adapters are registered yet; each arrives with its own task.
    """
    settings = settings or Settings()
    clock = SystemClock()
    secrets = KeyringSecretStore()
    events = create_event_store(settings.database_url)
    adapters: dict[str, SourceAdapter] = {}
    sync = SyncService(adapters, secrets, events, clock)
    return Container(
        sync=sync,
        agenda=AgendaService(events, clock, ZoneInfo(settings.tz)),
        settings=SettingsService(adapters, secrets, sync),
    )


def create_app() -> FastAPI:
    """The production app; its container is built at startup, not at import or construction."""
    return create_api_app(build_container)


def main() -> None:  # pragma: no cover - process entry point
    """Run the API on the configured host, which Settings restricts to loopback."""
    import uvicorn  # noqa: PLC0415

    settings = Settings()
    app = create_api_app(lambda: build_container(settings))
    uvicorn.run(app, host=settings.host, port=settings.port)
