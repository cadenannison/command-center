"""Connects and disconnects sources. Secrets go in and only their status comes back out."""

import asyncio
from collections.abc import Mapping

from command_center.core.errors import AuthExpired, FatalError, SecretStoreError, TransientError
from command_center.core.ports import IntegrationAdapter, SecretStore, SourceAdapter
from command_center.services.errors import UnknownSourceError, error_text, safe_message
from command_center.services.models import ConnectResult, SourceSettings, SyncState
from command_center.services.sync import STORE_UNAVAILABLE_MESSAGE, SyncService


class SettingsService:
    """Write-only credential management: status is set + last4 per key, never a value.

    Besides the sync sources it manages credential-only integrations (an API key): they are
    validated, stored, listed and deleted the same way, but they have no sync state, no
    events, and `SyncService` does not know them (decision 0058).
    """

    def __init__(
        self,
        adapters: Mapping[str, SourceAdapter],
        secrets: SecretStore,
        sync: SyncService,
        integrations: Mapping[str, IntegrationAdapter] | None = None,
    ) -> None:
        self._adapters = adapters
        self._integrations = dict(integrations or {})
        shared = self._integrations.keys() & adapters.keys()
        if shared:
            msg = f"Registered as both a source and an integration: {sorted(shared)}"
            raise ValueError(msg)
        self._secrets = secrets
        self._sync = sync

    async def status(self) -> list[SourceSettings]:
        """Settings of every registered source, then of every integration."""
        return [
            await self._source_settings(source) for source in (*self._adapters, *self._integrations)
        ]

    async def connect(self, source: str, creds: Mapping[str, str]) -> ConnectResult:
        """Validate the stored credentials overlaid by creds, store them; the caller then syncs.

        Submitted fields that are blank or only whitespace keep the stored value, so a field
        is cleared by disconnecting and reconnecting. The adapter validates the merged set.

        A successful result carries the source's state as "syncing". Running the sync is the
        caller's job (`SyncService.sync`), so connecting never waits for a slow source.

        A rejected credential is a result with ok false and nothing stored, not an exception.
        An integration's result carries no sync state, so the caller has nothing to sync.
        """
        adapter: SourceAdapter | IntegrationAdapter | None = self._adapters.get(
            source
        ) or self._integrations.get(source)
        if adapter is None:
            raise UnknownSourceError(source)
        try:
            stored = dict(await asyncio.to_thread(self._secrets.get, source))
        except SecretStoreError:
            return self._store_unavailable(source)
        merged = {**stored, **{key: value for key, value in creds.items() if value.strip()}}
        try:
            result = await adapter.validate(merged)
        except AuthExpired:
            return ConnectResult(source=source, ok=False, message="Credentials were rejected")
        except (TransientError, FatalError) as exc:
            message = f"Could not validate credentials: {error_text(exc)}"
            return ConnectResult(source=source, ok=False, message=safe_message(message))
        if not result.ok:
            return ConnectResult(source=source, ok=False, message=safe_message(result.message))
        final = {**merged, **(result.updated_creds or {})}
        try:
            for key, value in final.items():
                if stored.get(key) != value:
                    await asyncio.to_thread(self._secrets.set, source, key, value)
        except SecretStoreError:
            return self._store_unavailable(source)
        state = self._sync.mark_syncing(source) if source in self._adapters else None
        message = safe_message(result.message)
        return ConnectResult(source=source, ok=True, message=message, sync=state)

    def _store_unavailable(self, source: str) -> ConnectResult:
        state = self._unavailable_state(source)
        return ConnectResult(source=source, ok=False, message=state.message, sync=state)

    def _unavailable_state(self, source: str) -> SyncState:
        # An integration has no sync result to keep, so its error is reported, not remembered.
        if source in self._adapters:
            return self._sync.record_error(source, STORE_UNAVAILABLE_MESSAGE)
        return self._sync.error_state(source, STORE_UNAVAILABLE_MESSAGE)

    async def disconnect(self, source: str) -> SourceSettings:
        """Delete every stored key and stored event of source and forget its sync state."""
        if source not in self._adapters and source not in self._integrations:
            raise UnknownSourceError(source)
        try:
            await asyncio.to_thread(self._secrets.delete, source)
        except SecretStoreError:
            state = self._unavailable_state(source)
            return SourceSettings(source=source, keys={}, sync=state)
        if source in self._adapters:
            await self._sync.purge(source)
        return SourceSettings(source=source, keys={}, sync=None)

    async def _source_settings(self, source: str) -> SourceSettings:
        try:
            keys = await asyncio.to_thread(self._secrets.status, source)
        except SecretStoreError:
            state = self._sync.error_state(source, STORE_UNAVAILABLE_MESSAGE)
            return SourceSettings(source=source, keys={}, sync=state)
        sync = self._sync.state(source) if source in self._adapters else None
        return SourceSettings(source=source, keys=dict(keys), sync=sync)
