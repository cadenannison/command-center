"""The set of services a process serves; built by a composition root, consumed by the api."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from command_center.services.agenda import AgendaService
from command_center.services.chat import ChatService
from command_center.services.geocode import GeocodeService
from command_center.services.items import ItemService
from command_center.services.pairing import PairingService
from command_center.services.settings import SettingsService
from command_center.services.summary import SummaryService
from command_center.services.summary_control import SummaryControl
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
    # The stored opt-in and provider choice. None in a container built without one (tests, or a
    # process that cannot change the setting): then `summary` alone decides, as it always did.
    summary_control: SummaryControl | None = None
    # None answers 404 on the city search route. Last, so positional construction is unchanged.
    geocode: GeocodeService | None = None
    # None hides the item controls and answers 404 on the item and history routes (decision 0120).
    items: ItemService | None = None
    # None answers 404 on the chat routes. Even when built, chat sends nothing until the user opts
    # in: `ChatService` checks the stored switch before it builds a provider (decision 0160).
    chat: ChatService | None = None

    async def summary_service(self) -> SummaryService | None:
        """The service that may be called now: the control's when there is one, else `summary`.

        With a control, a summary switched off in the UI is off here even if `summary` was built
        at startup, so nothing is sent while it is disabled.
        """
        if self.summary_control is not None:
            return await self.summary_control.service()
        return self.summary
