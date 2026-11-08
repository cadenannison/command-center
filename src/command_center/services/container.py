"""The set of services a process serves; built by a composition root, consumed by the api."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from command_center.services.agenda import AgendaService
from command_center.services.pairing import PairingService
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.sync_control import SyncControl


@dataclass(frozen=True)
class Container:
    """The wired services."""

    sync: SyncControl
    agenda: AgendaService
    settings: SettingsService
    # None while summaries are off (the default): there is then no provider and no route data.
    summary: SummaryService | None = None
    # None leaves every non-loopback Host locked out: with no pairing there is no token to check.
    pairing: PairingService | None = None
    # Releases what the composition root opened (the distributed api's Redis connections); run
    # once at shutdown. None when there is nothing to release.
    close: Callable[[], Awaitable[None]] | None = None
