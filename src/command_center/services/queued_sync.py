"""The api's view of syncing in distributed mode: queue the work, read what the normalizer wrote.

Nothing here fetches. `sync` publishes a job for the source's worker; the worker reports; the
normalizer is the only writer of events and sync state (decisions 0070, 0071), so this class
writes neither, except to purge a disconnected source. A disconnect bumps the source's generation
first (`cancel`), which is what makes the normalizer drop any report still on its way (decision
0074); the purge comes last and bumps again (decisions 0085, 0086).
"""

import asyncio
import logging
from collections.abc import Sequence

from command_center.core.ports import Clock, EventStore, GenerationStore, SyncStateStore
from command_center.core.sync_state import SyncState, SyncStatus
from command_center.services.errors import UnknownSourceError, safe_message
from command_center.services.scheduler import SyncEnqueuer

logger = logging.getLogger(__name__)

SYNCING_MESSAGE = "Sync in progress"
QUEUE_FAILED_MESSAGE = "Could not queue the sync; it will be retried at the next scheduled round"


class QueuedSyncService:
    """SyncControl over a job queue and the shared stores."""

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        sources: Sequence[str],
        enqueuer: SyncEnqueuer,
        states: SyncStateStore,
        events: EventStore,
        generations: GenerationStore,
        clock: Clock,
    ) -> None:
        self._sources = tuple(sources)
        self._enqueuer = enqueuer
        self._states = states
        self._events = events
        self._generations = generations
        self._clock = clock

    def sources(self) -> list[str]:
        """Names of every registered source."""
        return list(self._sources)

    def state(self, source: str) -> SyncState | None:
        """What the normalizer last recorded for source, or None before its first report.

        A database error is also None (decision 0084), as in `SyncService.state`: one unreadable
        source must not turn the whole settings listing into a 500.
        """
        try:
            return self._states.get(source)
        except Exception as exc:  # noqa: BLE001  (a database error: the state is just unknown)
            # Class only: a database error can echo the connection URL, which holds a password.
            logger.warning(
                "sync state read failed for %s: %s",
                source,
                type(exc).__name__,
                extra={"source": source, "error_class": type(exc).__name__},
            )
            return None

    def mark_syncing(self, source: str) -> SyncState:
        """The "syncing" state for a connect's result. It is not stored (decision 0074).

        This process's clock must not stamp a stored state: the normalizer drops a report older
        than the stored one, and the worker's clock may be a little behind this one.
        """
        if source not in self._sources:
            raise UnknownSourceError(source)
        return self._unstored(source, "syncing", SYNCING_MESSAGE)

    def record_error(self, source: str, message: str) -> SyncState:
        """An error state for source. Like `mark_syncing`, it is returned and not stored."""
        return self.error_state(source, message)

    def error_state(self, source: str, message: str) -> SyncState:
        """An error state for source, to report without replacing its last sync result."""
        return self._unstored(source, "error", message)

    async def sync(self, source: str) -> SyncState:
        """Queue a sync job for source and return "syncing"; a queue failure is an error state."""
        if source not in self._sources:
            raise UnknownSourceError(source)
        try:
            await self._enqueuer.publish_one(source)
        except Exception as exc:  # noqa: BLE001  (a Redis or database error; only its class is logged)
            logger.warning(
                "could not queue a sync of %s: %s",
                source,
                type(exc).__name__,
                extra={"source": source, "error_class": type(exc).__name__},
            )
            return self.error_state(source, QUEUE_FAILED_MESSAGE)
        return self.mark_syncing(source)

    async def sync_all(self) -> list[SyncState]:
        """Queue a job for every connected source.

        Each queued source is reported as syncing; a connected source whose job could not be
        queued as an error state (not stored, like `sync`); the others as the normalizer last
        recorded them, left out when it recorded nothing. The results arrive later, through
        `state`.
        """
        outcome = await self._enqueuer.publish_outcome()
        states: list[SyncState] = []
        for source in self._sources:
            if source in outcome.published:
                states.append(self.mark_syncing(source))
            elif source in outcome.failed:
                states.append(self.error_state(source, QUEUE_FAILED_MESSAGE))
            elif (known := await asyncio.to_thread(self.state, source)) is not None:
                states.append(known)
        return states

    async def cancel(self, source: str) -> None:
        """Bump the source's generation, which cancels the work still in flight for it.

        It comes before anything is deleted: a report the normalizer is applying right now sees
        the bump after its write and deletes what it wrote (the normalizer's own check, decision
        0074). If it raises, the caller deletes nothing (decision 0085).
        """
        await asyncio.to_thread(self._generations.bump, source)

    async def purge(self, source: str) -> None:
        """Bump the generation again, then delete the source's events and sync state.

        The second bump invalidates a sync queued after `cancel` and before the credentials were
        deleted, whose report would otherwise be applied after this purge (decision 0086). A
        disconnect therefore ends on `cancel`'s number plus one.

        A failure leaves rows of the old generation behind; the normalizer's next apply or drop
        for the source deletes them (`ReportSink.purge_stale`), and a repeated disconnect does too.
        """
        await asyncio.to_thread(self._generations.bump, source)
        await asyncio.to_thread(self._events.delete_source, source)
        await asyncio.to_thread(self._states.delete, source)

    def _unstored(self, source: str, status: SyncStatus, message: str) -> SyncState:
        return SyncState(
            source=source, status=status, message=safe_message(message), at=self._clock.now()
        )
