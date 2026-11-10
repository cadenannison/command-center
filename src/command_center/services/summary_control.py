"""The stored AI-summary opt-in and provider choice, and the SummaryService built from them."""

import asyncio
from collections.abc import Callable

from command_center.core.ports import AppSettingStore
from command_center.services.errors import UnknownSummaryProviderError
from command_center.services.summary import SummaryService

ENABLED_KEY = "summary.enabled"
PROVIDER_KEY = "summary.provider"
PROVIDERS = ("gemini", "ollama")
_ON = "on"
_OFF = "off"


class SummaryControl:
    """Whether summaries are on and which provider they use, kept in the app-setting store.

    The environment values are only the defaults for a user who never changed the setting. With
    summaries off `service()` is None, so no provider is built and nothing is sent anywhere
    (decision 0004). Anything unreadable in the store counts as off.
    """

    def __init__(
        self,
        store: AppSettingStore,
        build: Callable[[str], SummaryService],
        *,
        default_enabled: bool,
        default_provider: str,
        forget_today: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._build = build
        self._default_enabled = default_enabled
        self._default_provider = default_provider
        self._forget_today = forget_today
        self._built: tuple[str, SummaryService] | None = None

    async def enabled(self) -> bool:
        """True when the user opted in (stored value), else the environment default."""
        stored = await asyncio.to_thread(self._store.get, ENABLED_KEY)
        if stored is None:
            return self._default_enabled
        return stored == _ON

    async def provider(self) -> str:
        """The chosen provider name, one of PROVIDERS."""
        stored = await asyncio.to_thread(self._store.get, PROVIDER_KEY)
        if stored in PROVIDERS:
            return stored
        return self._default_provider

    async def set_enabled(self, *, enabled: bool) -> None:
        """Turn summaries on or off."""
        await asyncio.to_thread(self._store.set, ENABLED_KEY, _ON if enabled else _OFF)

    async def set_provider(self, provider: str) -> None:
        """Choose the provider; an unknown name raises UnknownSummaryProviderError.

        A different provider drops today's stored summary (`forget_today`): the store is shared and
        a summary is labelled with the provider that is current when it is read, so one written by
        the old provider would otherwise carry the new one's name (decision 0115).
        """
        if provider not in PROVIDERS:
            raise UnknownSummaryProviderError(provider)
        changed = provider != await self.provider()
        await asyncio.to_thread(self._store.set, PROVIDER_KEY, provider)
        if changed and self._forget_today is not None:
            await asyncio.to_thread(self._forget_today)

    async def service(self) -> SummaryService | None:
        """The summary service for the current setting; None while summaries are off."""
        if not await self.enabled():
            return None
        provider = await self.provider()
        built = self._built
        if built is None or built[0] != provider:
            # No await between this check and the assignment, so two callers cannot interleave.
            built = (provider, self._build(provider))
            self._built = built
        return built[1]
