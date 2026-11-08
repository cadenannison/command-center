"""The set of services a process serves; built by a composition root, consumed by the api."""

from dataclasses import dataclass

from command_center.services.agenda import AgendaService
from command_center.services.pairing import PairingService
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.sync import SyncService


@dataclass(frozen=True)
class Container:
    """The wired services."""

    sync: SyncService
    agenda: AgendaService
    settings: SettingsService
    # None while summaries are off (the default): there is then no provider and no route data.
    summary: SummaryService | None = None
    # None leaves every non-loopback Host locked out: with no pairing there is no token to check.
    pairing: PairingService | None = None
