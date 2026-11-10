"""Connects and disconnects sources. Secrets go in and only their status comes back out."""

import asyncio
import logging
from collections.abc import Mapping, Sequence

from command_center.core.errors import AuthExpired, FatalError, SecretStoreError, TransientError
from command_center.core.ports import Clock, IntegrationAdapter, SecretStore, SourceAdapter
from command_center.core.schema import SecretStatus, ValidationResult
from command_center.services.credential_fields import is_secret
from command_center.services.errors import UnknownSourceError, error_text, safe_message
from command_center.services.models import ConnectResult, SourceSettings, SyncState
from command_center.services.setup_checklist import SetupItem, build_checklist
from command_center.services.sync import STORE_UNAVAILABLE_MESSAGE
from command_center.services.sync_control import SyncControl

logger = logging.getLogger(__name__)

DISCONNECT_FAILED_MESSAGE = "Could not disconnect; nothing was removed. Try again"
DISCONNECT_INCOMPLETE_MESSAGE = (
    "Disconnect incomplete: the credentials are gone but some stored data is not. "
    "Disconnect again to finish"
)
UNVERIFIED_PREFIX = "Saved unverified:"
UNVERIFIED_MESSAGE = (
    f"{UNVERIFIED_PREFIX} the credentials were not checked. "
    "Use Test connection once the network works"
)
NOTHING_TO_SAVE_MESSAGE = "Nothing was entered, so nothing was saved"
NOT_CONNECTED_MESSAGE = "Nothing is stored for this source yet; connect it first"


class SettingsService:
    """Write-only credential management: status is set + last4 per key, never a value.

    Besides the sync sources it manages credential-only integrations (an API key): they are
    validated, stored, listed and deleted the same way, but they have no sync state, no
    events, and the sync service does not know them (decision 0058).
    """

    def __init__(
        self,
        adapters: Mapping[str, SourceAdapter],
        secrets: SecretStore,
        sync: SyncControl,
        integrations: Mapping[str, IntegrationAdapter] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._adapters = adapters
        self._integrations = dict(integrations or {})
        shared = self._integrations.keys() & adapters.keys()
        if shared:
            msg = f"Registered as both a source and an integration: {sorted(shared)}"
            raise ValueError(msg)
        self._secrets = secrets
        self._sync = sync
        self._clock = clock

    async def status(self) -> list[SourceSettings]:
        """Settings of every registered source, then of every integration."""
        return [
            await self._source_settings(source) for source in (*self._adapters, *self._integrations)
        ]

    def checklist(self, items: Sequence[SourceSettings]) -> list[SetupItem]:
        """The setup checklist for items (from `status`); ages are None without a clock."""
        return build_checklist(items, None if self._clock is None else self._clock.now())

    async def connect(self, source: str, creds: Mapping[str, str]) -> ConnectResult:
        """Validate the stored credentials overlaid by creds, store them; the caller then syncs.

        Submitted fields that are blank or only whitespace keep the stored value, so a field
        is cleared by disconnecting and reconnecting. The adapter validates the merged set.

        A successful result carries the source's state as "syncing". Running the sync is the
        caller's job (`SyncControl.sync`; in distributed mode that queues a job for the workers),
        so connecting never waits for a slow source.

        A rejected credential is a result with ok false and nothing stored, not an exception.
        Its `can_save_unverified` is true only after a TransientError (decision 0101).
        An integration's result carries no sync state, so the caller has nothing to sync.
        """
        adapter = self._adapter(source)
        try:
            stored = dict(await asyncio.to_thread(self._secrets.get, source))
        except SecretStoreError:
            return self._store_unavailable(source)
        merged = _overlay(stored, creds)
        checked = await _check(adapter, source, merged)
        if isinstance(checked, ConnectResult):
            return checked
        final = {**merged, **(checked.updated_creds or {})}
        if not await self._write(source, stored, final):
            return self._store_unavailable(source)
        state = self._sync.mark_syncing(source) if source in self._adapters else None
        return ConnectResult(
            source=source, ok=True, message=safe_message(checked.message), sync=state
        )

    async def save_unverified(self, source: str, creds: Mapping[str, str]) -> ConnectResult:
        """Store the stored credentials overlaid by creds without validating them.

        For a network failure that stopped `connect` from checking them (decision 0101). A source
        is left in an "error" state whose message starts with UNVERIFIED_PREFIX; no sync is queued,
        so the caller must not sync. In distributed mode that state is not stored, so it shows in
        this result only. An integration has no sync state to leave.
        """
        self._adapter(source)
        if not any(value.strip() for value in creds.values()):
            return ConnectResult(source=source, ok=False, message=NOTHING_TO_SAVE_MESSAGE)
        try:
            stored = dict(await asyncio.to_thread(self._secrets.get, source))
        except SecretStoreError:
            return self._store_unavailable(source)
        if not await self._write(source, stored, _overlay(stored, creds)):
            return self._store_unavailable(source)
        state = None
        if source in self._adapters:
            state = self._sync.record_error(source, UNVERIFIED_MESSAGE)
        return ConnectResult(source=source, ok=True, message=UNVERIFIED_MESSAGE, sync=state)

    async def check_connection(self, source: str) -> ConnectResult:
        """Validate the stored credentials without changing them, and report the redacted result.

        A refreshed credential the adapter returns is stored, as `connect` would. No sync state is
        written and no sync is queued, so the result's `sync` is None.
        """
        adapter = self._adapter(source)
        try:
            stored = dict(await asyncio.to_thread(self._secrets.get, source))
        except SecretStoreError:
            return self._store_unavailable(source)
        if not stored:
            return ConnectResult(source=source, ok=False, message=NOT_CONNECTED_MESSAGE)
        checked = await _check(adapter, source, stored)
        if isinstance(checked, ConnectResult):
            return checked
        final = {**stored, **(checked.updated_creds or {})}
        if not await self._write(source, stored, final):
            return self._store_unavailable(source)
        return ConnectResult(source=source, ok=True, message=safe_message(checked.message))

    def _adapter(self, source: str) -> SourceAdapter | IntegrationAdapter:
        adapter = self._adapters.get(source) or self._integrations.get(source)
        if adapter is None:
            raise UnknownSourceError(source)
        return adapter

    async def _write(
        self, source: str, stored: Mapping[str, str], final: Mapping[str, str]
    ) -> bool:
        """Store the keys of final that differ from stored; False if the secret store failed."""
        try:
            for key, value in final.items():
                if stored.get(key) != value:
                    await asyncio.to_thread(self._secrets.set, source, key, value)
        except SecretStoreError:
            return False
        return True

    def _store_unavailable(self, source: str) -> ConnectResult:
        state = self._unavailable_state(source)
        return ConnectResult(source=source, ok=False, message=state.message, sync=state)

    def _unavailable_state(self, source: str) -> SyncState:
        # An integration has no sync result to keep, so its error is reported, not remembered.
        if source in self._adapters:
            return self._sync.record_error(source, STORE_UNAVAILABLE_MESSAGE)
        return self._sync.error_state(source, STORE_UNAVAILABLE_MESSAGE)

    async def disconnect(self, source: str) -> SourceSettings:
        """Delete every stored key and stored event of source and forget its sync state.

        The order is cancel, secrets, purge (decision 0085). If the cancel fails nothing has been
        deleted and the result carries an error state. If the purge fails the credentials are
        already gone: the result says the disconnect is incomplete, and disconnecting again
        finishes it. Rows the purge missed are also removed by the normalizer's next apply or
        drop for the source, which compares their generation.
        """
        if source not in self._adapters and source not in self._integrations:
            raise UnknownSourceError(source)
        is_source = source in self._adapters
        if is_source:
            try:
                await self._sync.cancel(source)
            except Exception as exc:  # noqa: BLE001  (a database error; only its class is logged)
                _log_failure("cancel", source, exc)
                state = self._sync.error_state(source, DISCONNECT_FAILED_MESSAGE)
                return SourceSettings(source=source, keys=await self._keys(source), sync=state)
        try:
            await asyncio.to_thread(self._secrets.delete, source)
        except SecretStoreError:
            state = self._unavailable_state(source)
            return SourceSettings(source=source, keys={}, sync=state)
        if is_source:
            try:
                await self._sync.purge(source)
            except Exception as exc:  # noqa: BLE001  (a database error; only its class is logged)
                _log_failure("purge", source, exc)
                state = self._sync.error_state(source, DISCONNECT_INCOMPLETE_MESSAGE)
                return SourceSettings(source=source, keys={}, sync=state)
        return SourceSettings(source=source, keys={}, sync=None)

    async def _keys(self, source: str) -> dict[str, SecretStatus]:
        try:
            return dict(await asyncio.to_thread(self._secrets.status, source))
        except SecretStoreError:
            return {}

    async def _source_settings(self, source: str) -> SourceSettings:
        try:
            keys = await asyncio.to_thread(self._secrets.status, source)
            values = await self._plain_values(source, keys)
        except SecretStoreError:
            state = self._sync.error_state(source, STORE_UNAVAILABLE_MESSAGE)
            return SourceSettings(source=source, keys={}, sync=state)
        sync = None
        if source in self._adapters:
            # The distributed api reads the database here, so it runs off the event loop.
            sync = await asyncio.to_thread(self._sync.state, source)
        return SourceSettings(source=source, keys=dict(keys), sync=sync, values=values)

    async def _plain_values(self, source: str, keys: Mapping[str, SecretStatus]) -> dict[str, str]:
        """The stored values of the non-secret keys that are set; a secret is never read here."""
        plain = [key for key, status in keys.items() if status.set and not is_secret(source, key)]
        if not plain:
            return {}
        stored = await asyncio.to_thread(self._secrets.get, source)
        return {key: stored[key] for key in plain if key in stored}


def _overlay(stored: Mapping[str, str], creds: Mapping[str, str]) -> dict[str, str]:
    """stored with every non-blank value of creds laid over it."""
    return {**stored, **{key: value for key, value in creds.items() if value.strip()}}


async def _check(
    adapter: SourceAdapter | IntegrationAdapter, source: str, creds: Mapping[str, str]
) -> ValidationResult | ConnectResult:
    """The adapter's accepted result, or the failed ConnectResult to hand back as it is."""
    try:
        result = await adapter.validate(creds)
    except AuthExpired:
        return ConnectResult(source=source, ok=False, message="Credentials were rejected")
    except (TransientError, FatalError) as exc:
        message = safe_message(f"Could not validate credentials: {error_text(exc)}")
        return ConnectResult(
            source=source,
            ok=False,
            message=message,
            can_save_unverified=isinstance(exc, TransientError),
        )
    if not result.ok:
        return ConnectResult(source=source, ok=False, message=safe_message(result.message))
    return result


def _log_failure(step: str, source: str, exc: Exception) -> None:
    # Class only: a database error can echo the connection URL, which holds a password.
    logger.warning(
        "disconnect of %s failed at %s: %s",
        source,
        step,
        type(exc).__name__,
        extra={"source": source, "step": step, "error_class": type(exc).__name__},
    )
