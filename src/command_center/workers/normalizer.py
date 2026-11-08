"""Applies sync reports to the stores: the one writer of what workers fetch (decision 0071).

Applying a report is idempotent: `EventStore.replace` swaps the source's events in the window for
the report's, and the state written is the report's own (its `at`, not this process's clock), so a
redelivered report leaves identical stored state.

A report carries the generation of the job that made it. A disconnect bumps the source's
generation, so a report from before it is dropped (decision 0074).

With a `ReportSink` (every composition root passes one, decision 0075) the generation check and the
writes are one transaction, the rows are stamped with the generation, and dropping a report also
deletes the source's rows from an older generation, so a crash between a write and the check
that follows it is cleaned up when the report is redelivered. Without a sink the stores are
written one after another and the second check can only undo, which is the 0074 behaviour that
tests and tools building a `Normalizer` by hand still get.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from command_center.core.jobs import SyncReport
from command_center.core.ports import (
    EventStore,
    GenerationStore,
    ReportSink,
    ReportStream,
    SyncStateStore,
)
from command_center.core.sync_state import SyncState
from command_center.services.errors import safe_message

logger = logging.getLogger(__name__)

type Sleep = Callable[[float], Awaitable[None]]


class Normalizer:
    """Consumes reports: `replace` the events of an ok report, then record the source's state."""

    def __init__(  # noqa: PLR0913
        self,
        reports: ReportStream,
        events: EventStore,
        states: SyncStateStore,
        *,
        consumer: str,
        generations: GenerationStore | None = None,
        sink: ReportSink | None = None,
        group: str = "normalizers",
        block_ms: int = 1000,
        poll_seconds: float = 1.0,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._reports = reports
        self._events = events
        self._states = states
        self._generations = generations
        self._sink = sink
        self._consumer = consumer
        self._group = group
        self._block_ms = block_ms
        self._poll_seconds = poll_seconds
        self._sleep = sleep

    async def run(self) -> None:
        """Apply reports until cancelled; a failed pass is logged by class and retried later."""
        while True:
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001  (a database or Redis error: the report is redelivered)
                logger.warning(
                    "normalizer pass failed: %s",
                    type(exc).__name__,
                    extra={"error_class": type(exc).__name__, "consumer": self._consumer},
                )
                await self._sleep(self._poll_seconds)

    async def run_once(self) -> bool:
        """Take and apply at most one report; True if there was one.

        Any exception except the permanent `ValueError` propagates with the report unacked, so the
        stream redelivers it after its visibility timeout.
        """
        report = await self._reports.consume(self._group, self._consumer, self._block_ms)
        if report is None:
            return False
        await self._apply(report)
        return True

    async def _apply(self, report: SyncReport) -> None:
        if self._sink is not None:
            await self._apply_atomically(self._sink, report)
        else:
            await self._apply_separately(report)

    async def _apply_atomically(self, sink: ReportSink, report: SyncReport) -> None:
        extra = {"source": report.source, "correlation_id": report.correlation_id}
        message = report.message
        if report.status == "ok":
            message = f"Synced {len({e.id for e in report.events})} items"
        state = SyncState(
            source=report.source,
            status=report.status,
            message=safe_message(message),
            at=report.at,
        )
        try:
            outcome = await asyncio.to_thread(
                sink.apply,
                report.generation,
                report.window,
                list(report.events) if report.status == "ok" else None,
                state,
            )
        except ValueError as exc:
            await self._reject(report, exc, extra)
            return
        if outcome == "not_current":
            logger.info("report from another generation dropped for %s", report.source, extra=extra)
            await asyncio.to_thread(sink.purge_stale, report.source)
        elif outcome == "older":
            # A redelivered older fetch must not overwrite the newer one already applied.
            logger.info("stale report ignored for %s", report.source, extra=extra)
        elif await self._superseded(report):
            # A disconnect's bump landed after our transaction began, so its purge may have run
            # before our writes. Our rows are from the old generation: delete exactly those.
            logger.info("disconnect during apply, undone for %s", report.source, extra=extra)
            await asyncio.to_thread(sink.purge_stale, report.source)
        await self._reports.ack(report)

    async def _reject(self, report: SyncReport, exc: ValueError, extra: dict[str, str]) -> None:
        # An event of another source or user: no redelivery can fix that.
        error_class = type(exc).__name__
        # Not logger.exception: the traceback can echo event text.
        logger.error(
            "report for %s rejected: %s",
            report.source,
            error_class,
            extra={**extra, "error_class": error_class},
        )
        await self._reports.dead_letter(report, error_class)

    async def _apply_separately(self, report: SyncReport) -> None:
        extra = {"source": report.source, "correlation_id": report.correlation_id}
        if await self._superseded(report):
            logger.info(
                "report from before a disconnect dropped for %s", report.source, extra=extra
            )
            await self._reports.ack(report)
            return
        current = await asyncio.to_thread(self._states.get, report.source)
        if current is not None and report.at < current.at:
            # A redelivered older fetch must not overwrite the newer one already applied.
            logger.info("stale report ignored for %s", report.source, extra=extra)
            await self._reports.ack(report)
            return
        message = report.message
        if report.status == "ok":
            try:
                written = await asyncio.to_thread(
                    self._events.replace, report.source, report.window, list(report.events)
                )
            except ValueError as exc:
                await self._reject(report, exc, extra)
                return
            message = f"Synced {written} items"
        state = SyncState(
            source=report.source,
            status=report.status,
            message=safe_message(message),
            at=report.at,
        )
        await asyncio.to_thread(self._states.put, state)
        if await self._superseded(report):
            # A disconnect landed while this report was being applied: its purge may have run
            # before our writes, so undo them. The bump came before the purge, so we see it here.
            logger.info("disconnect during apply, undone for %s", report.source, extra=extra)
            await asyncio.to_thread(self._events.delete_source, report.source)
            await asyncio.to_thread(self._states.delete, report.source)
        await self._reports.ack(report)

    async def _superseded(self, report: SyncReport) -> bool:
        """Whether the source was disconnected after the job behind this report was queued."""
        if self._generations is None:
            return False
        current = await asyncio.to_thread(self._generations.current, report.source)
        return current > report.generation
