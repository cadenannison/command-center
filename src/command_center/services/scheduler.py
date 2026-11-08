"""Keeps the sources fresh: one sync of everything at startup, then one per interval."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from command_center.services.sync import SyncService

logger = logging.getLogger(__name__)

type Sleep = Callable[[float], Awaitable[None]]


class SyncScheduler:
    """Runs `SyncService.sync_all` now and then every `interval_minutes`, until stopped.

    A failed round is logged by its exception class and the loop carries on; nothing a sync raises
    can end it. The summary is not scheduled: it is built on first request (decision 0053).
    """

    def __init__(
        self, sync: SyncService, interval_minutes: int, *, sleep: Sleep = asyncio.sleep
    ) -> None:
        self._sync = sync
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
            await self._sync.sync_all()
        except Exception as exc:  # noqa: BLE001  (SyncService re-raises bugs; a bug must not end the loop)
            # Class only: the message of an unexpected error may carry a URL or a credential.
            logger.warning(
                "scheduled sync failed: %s",
                type(exc).__name__,
                extra={"reason": type(exc).__name__},
            )
