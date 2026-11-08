"""Keeps the sources fresh: one sync of everything at startup, then one per interval.

In distributed mode (decision 0070) a round publishes one sync job per connected source instead
of syncing in this process; the workers do the fetching.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC

from command_center.core.jobs import Job
from command_center.core.ports import Clock, GenerationStore, IdSource, JobQueue, SecretStore
from command_center.services.horizon import horizon_window
from command_center.services.sync_control import SyncControl

logger = logging.getLogger(__name__)

type Sleep = Callable[[float], Awaitable[None]]


SYNC_JOB_KIND = "sync"


class SyncEnqueuer:
    """Publishes one sync job per connected source to that source's queue.

    A source is connected when the secret store holds credentials for it. The job carries the
    horizon window and ids, never a credential: the worker reads those itself. One queue per
    source is what lets one worker consume one source (decision 0070). With `generations` each
    job carries the source's generation as it is when the job is published, so work queued before
    a disconnect is told apart from work queued after it (decision 0074).
    """

    def __init__(  # noqa: PLR0913
        self,
        sources: Sequence[str],
        secrets: SecretStore,
        queues: Mapping[str, JobQueue],
        clock: Clock,
        ids: IdSource,
        *,
        generations: GenerationStore | None = None,
    ) -> None:
        self._sources = tuple(sources)
        self._generations = generations
        self._secrets = secrets
        self._queues = queues
        self._clock = clock
        self._ids = ids

    async def publish_round(self) -> int:
        """Publish a job for every connected source; return how many were published."""
        return len(await self.publish_connected())

    async def publish_connected(self) -> list[str]:
        """Publish a job for every connected source and name the sources that got one.

        One source failing (store unreadable, queue down: any exception) is logged by its class
        and does not stop the others.
        """
        published: list[str] = []
        for source in self._sources:
            try:
                # The generation is read before the credentials: a disconnect that lands in between
                # then leaves a job with the old number, which the normalizer drops.
                generation = await self._generation(source)
                creds = await asyncio.to_thread(self._secrets.get, source)
                if not creds:
                    continue
                await self._queues[source].publish(self._job(source, generation))
            except Exception as exc:  # noqa: BLE001  (not a builtin for Redis; class logged)
                logger.warning(
                    "could not enqueue a sync of %s: %s",
                    source,
                    type(exc).__name__,
                    extra={"source": source, "error_class": type(exc).__name__},
                )
                continue
            published.append(source)
        return published

    async def publish_one(self, source: str) -> None:
        """Publish a sync job for one source, connected or not; the worker reports "reconnect"
        for a source with no credentials. Errors from the store or the queue propagate."""
        await self._queues[source].publish(self._job(source, await self._generation(source)))

    async def _generation(self, source: str) -> int:
        if self._generations is None:
            return 0
        return await asyncio.to_thread(self._generations.current, source)

    def _job(self, source: str, generation: int = 0) -> Job:
        window = horizon_window(self._clock.now().astimezone(UTC))
        return Job(
            id=self._ids.new_id(),
            kind=SYNC_JOB_KIND,
            source=source,
            window=window,
            correlation_id=self._ids.new_id(),
            generation=generation,
        )


class SyncScheduler:
    """Runs a sync round now and then every `interval_minutes`, until stopped.

    A round is `SyncControl.sync_all`, or, with `enqueue`, `SyncEnqueuer.publish_round` (the
    single-process mode is unchanged). A failed round is logged by its exception class and the
    loop carries on; nothing a round raises can end it. The summary is not scheduled: it is built
    on first request (decision 0053).
    """

    def __init__(
        self,
        sync: SyncControl | None,
        interval_minutes: int,
        *,
        sleep: Sleep = asyncio.sleep,
        enqueue: SyncEnqueuer | None = None,
    ) -> None:
        if (sync is None) == (enqueue is None):
            msg = "SyncScheduler needs exactly one of a SyncControl or a SyncEnqueuer"
            raise ValueError(msg)
        self._sync = sync
        self._enqueue = enqueue
        self._interval_seconds = interval_minutes * 60
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the loop on the running event loop; a second call does nothing."""
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name="sync-scheduler")

    async def stop(self) -> None:
        """Cancel the loop and wait for it to end."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def run(self) -> None:
        """Sync, wait one interval, repeat. Ends only when cancelled."""
        while True:
            await self._round()
            await self._sleep(self._interval_seconds)

    async def _round(self) -> None:
        try:
            if self._enqueue is not None:
                await self._enqueue.publish_round()
            elif self._sync is not None:
                await self._sync.sync_all()
        except Exception as exc:  # noqa: BLE001  (SyncService re-raises bugs; a bug must not end the loop)
            # Class only: the message of an unexpected error may carry a URL or a credential.
            logger.warning(
                "scheduled sync failed: %s",
                type(exc).__name__,
                extra={"reason": type(exc).__name__, "error_class": type(exc).__name__},
            )
