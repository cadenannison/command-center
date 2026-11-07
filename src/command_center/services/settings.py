"""Connects and disconnects sources. Secrets go in and only their status comes back out."""

import asyncio
from collections.abc import Mapping

from command_center.core.errors import AuthExpired, FatalError, SecretStoreError, TransientError
from command_center.core.ports import SecretStore, SourceAdapter
from command_center.services.errors import UnknownSourceError, describe
from command_center.services.models import ConnectResult, SourceSettings
from command_center.services.sync import STORE_UNAVAILABLE_MESSAGE, SyncService


class SettingsService:
    """Write-only credential management: status is set + last4 per key, never a value."""

    def __init__(
        self,
        adapters: Mapping[str, SourceAdapter],
        secrets: SecretStore,
        sync: SyncService,
    ) -> None:
        self._adapters = adapters
        self._secrets = secrets
        self._sync = sync

    async def status(self) -> list[SourceSettings]:
        """Settings of every registered source."""
        return [await self._source_settings(source) for source in self._adapters]

    async def connect(self, source: str, creds: Mapping[str, str]) -> ConnectResult:
        """Validate creds and store them (merged key by key); the caller then runs the sync.

        A successful result carries the source's state as "syncing". Running the sync is the
        caller's job (`SyncService.sync`), so connecting never waits for a slow source.

        A rejected credential is a result with ok false and nothing stored, not an exception.
        """
        adapter = self._adapters.get(source)
        if adapter is None:
            raise UnknownSourceError(source)
        try:
            result = await adapter.validate(creds)
        except AuthExpired:
            return ConnectResult(source=source, ok=False, message="Credentials were rejected")
        except (TransientError, FatalError) as exc:
            message = f"Could not validate credentials: {describe(exc)}"
            return ConnectResult(source=source, ok=False, message=message)
        if not result.ok:
            return ConnectResult(source=source, ok=False, message=result.message)
        merged = {**creds, **(result.updated_creds or {})}
        try:
            for key, value in merged.items():
                await asyncio.to_thread(self._secrets.set, source, key, value)
        except SecretStoreError:
            state = self._sync.record_error(source, STORE_UNAVAILABLE_MESSAGE)
            return ConnectResult(source=source, ok=False, message=state.message, sync=state)
        state = self._sync.mark_syncing(source)
        return ConnectResult(source=source, ok=True, message=result.message, sync=state)

    async def disconnect(self, source: str) -> SourceSettings:
        """Delete every stored key and stored event of source and forget its sync state."""
        if source not in self._adapters:
            raise UnknownSourceError(source)
        try:
            await asyncio.to_thread(self._secrets.delete, source)
        except SecretStoreError:
            state = self._sync.record_error(source, STORE_UNAVAILABLE_MESSAGE)
            return SourceSettings(source=source, keys={}, sync=state)
        await self._sync.purge(source)
        return SourceSettings(source=source, keys={}, sync=None)

    async def _source_settings(self, source: str) -> SourceSettings:
        try:
            keys = await asyncio.to_thread(self._secrets.status, source)
        except SecretStoreError:
            state = self._sync.error_state(source, STORE_UNAVAILABLE_MESSAGE)
            return SourceSettings(source=source, keys={}, sync=state)
        return SourceSettings(source=source, keys=dict(keys), sync=self._sync.state(source))
