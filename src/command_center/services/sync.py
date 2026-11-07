"""Pulls each source's items into the event store and remembers how the last attempt went."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC

from command_center.core.errors import AuthExpired, FatalError, SecretStoreError, TransientError
from command_center.core.ports import Clock, EventStore, SecretStore, SourceAdapter
from command_center.core.schema import Event
from command_center.core.windows import TimeWindow
from command_center.services.errors import UnknownSourceError, describe
from command_center.services.horizon import horizon_window
from command_center.services.models import SyncState, SyncStatus

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0
UNEXPECTED_MESSAGE = "Sync failed unexpectedly"
STORE_UNAVAILABLE_MESSAGE = "secret store unavailable"  # fixed text: the cause may name a source

type Sleep = Callable[[float], Awaitable[None]]


class SyncService:
    """Fetches from source adapters over the sync window and replaces the source's events."""

    def __init__(
        self,
        adapters: Mapping[str, SourceAdapter],
        secrets: SecretStore,
        events: EventStore,
        clock: Clock,
        *,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._adapters = adapters
        self._secrets = secrets
        self._events = events
        self._clock = clock
        self._sleep = sleep
        self._states: dict[str, SyncState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._forgotten: dict[str, int] = {}  # how often each source was forgotten

    def sources(self) -> list[str]:
        """Names of every registered source."""
        return list(self._adapters)

    def state(self, source: str) -> SyncState | None:
        """The last sync result of source, or None if it has not been synced in this process."""
        return self._states.get(source)

    def forget(self, source: str) -> None:
        """Drop the remembered sync result of source (after a disconnect).

        A sync already running for source finishes without remembering its result (decision 0026).
        """
        self._forgotten[source] = self._forgotten.get(source, 0) + 1
        self._states.pop(source, None)

    async def purge(self, source: str) -> None:
        """Forget source's sync result and delete its stored events (after a disconnect).

        Forgetting comes first, so a sync still running deletes what it writes late (0029).
        """
        self.forget(source)
        await asyncio.to_thread(self._events.delete_source, source)

    def error_state(self, source: str, message: str) -> SyncState:
        """An error state for source, to report without replacing its last sync result."""
        return SyncState(source=source, status="error", message=message, at=self._clock.now())

    def mark_syncing(self, source: str) -> SyncState:
        """Record that source is syncing, so a reader sees it before the sync has begun."""
        if source not in self._adapters:
            raise UnknownSourceError(source)
        return self._remember(source, "syncing", "Sync in progress")

    def record_error(self, source: str, message: str) -> SyncState:
        """Remember an error state for source that did not come from a sync attempt."""
        state = self.error_state(source, message)
        self._states[source] = state
        return state

    async def sync(self, source: str) -> SyncState:
        """Sync one source and return its new state; an unknown source is an UnknownSourceError.

        Failures of the source are reported in the returned state, never raised.
        """
        adapter = self._adapters.get(source)
        if adapter is None:
            raise UnknownSourceError(source)
        lock = self._locks.setdefault(source, asyncio.Lock())
        async with lock:
            self.mark_syncing(source)
            forgotten = self._forgotten.get(source, 0)
            try:
                state = await self._sync_locked(source, adapter)
            except Exception:
                # A bug must not leave the source "syncing" forever.
                self._remember(source, "error", UNEXPECTED_MESSAGE)
                try:
                    await self._discard_if_forgotten(source, forgotten)
                except Exception:
                    # The sync's own failure is the one the caller needs to see.
                    logger.exception(
                        "cleanup of %s after a failed sync also failed",
                        source,
                        extra={"source": source},
                    )
                raise
            await self._discard_if_forgotten(source, forgotten)
            return state

    async def _discard_if_forgotten(self, source: str, forgotten_before: int) -> None:
        if self._forgotten.get(source, 0) != forgotten_before:
            self._states.pop(source, None)
            # The disconnect may have deleted the events before this sync wrote them (0029).
            await asyncio.to_thread(self._events.delete_source, source)

    async def sync_all(self) -> list[SyncState]:
        """Sync every source concurrently; one source's failure does not affect the others."""
        return list(await asyncio.gather(*(self.sync(source) for source in self._adapters)))

    async def _sync_locked(self, source: str, adapter: SourceAdapter) -> SyncState:
        try:
            creds = await asyncio.to_thread(self._secrets.get, source)
        except SecretStoreError:
            logger.warning(
                "sync skipped for %s: secret store unavailable", source, extra={"source": source}
            )
            return self._remember(source, "error", STORE_UNAVAILABLE_MESSAGE)
        if not creds:
            return self._remember(source, "reconnect", "Not connected: no credentials stored")
        window = horizon_window(self._clock.now().astimezone(UTC))
        try:
            fetched = await self._fetch_with_retry(source, adapter, creds, window)
        except AuthExpired:
            logger.warning("sync of %s needs reconnect", source, extra={"source": source})
            return self._remember(source, "reconnect", "Credentials were rejected; reconnect")
        except TransientError as exc:
            message = f"Source unreachable after {MAX_RETRIES} retries: {describe(exc)}"
            logger.warning(
                "sync of %s gave up: %s", source, describe(exc), extra={"source": source}
            )
            return self._remember(source, "error", message)
        except FatalError as exc:
            logger.warning("sync of %s failed: %s", source, describe(exc), extra={"source": source})
            return self._remember(source, "error", f"Sync failed: {describe(exc)}")
        # Only a fully fetched result gets here: replace deletes whatever it does not contain.
        written = await asyncio.to_thread(self._events.replace, source, window, fetched)
        return self._remember(source, "ok", f"Synced {written} items")

    async def _fetch_with_retry(
        self,
        source: str,
        adapter: SourceAdapter,
        creds: Mapping[str, str],
        window: TimeWindow,
    ) -> list[Event]:
        """Fetch, retrying only TransientError (a read, so repeating it is safe), up to a cap."""
        attempt = 0
        while True:
            try:
                return await adapter.fetch(creds, window)
            except TransientError as exc:
                if attempt >= MAX_RETRIES:
                    raise
                delay = BACKOFF_BASE_SECONDS * 2**attempt
                attempt += 1
                logger.warning(
                    "sync of %s retry %d in %.0fs: %s",
                    source,
                    attempt,
                    delay,
                    describe(exc),
                    extra={
                        "source": source,
                        "attempt": attempt,
                        "delay_seconds": delay,
                        "reason": describe(exc),
                    },
                )
                await self._sleep(delay)

    def _remember(self, source: str, status: SyncStatus, message: str) -> SyncState:
        state = SyncState(source=source, status=status, message=message, at=self._clock.now())
        self._states[source] = state
        return state
