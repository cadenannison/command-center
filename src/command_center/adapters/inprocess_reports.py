"""In-process ReportStream for tests and hermetic chaos runs. Decision: 0071."""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from command_center.core.jobs import MAX_REASON_LENGTH, DeadReport, SyncReport
from command_center.core.ports import Clock
from command_center.core.redact import trim
from command_center.core.resilience import DEFAULT_VISIBILITY_TIMEOUT

logger = logging.getLogger(__name__)

DEFAULT_MAX_DELIVERIES = 5
DELIVERIES_EXHAUSTED_REASON = "delivered too many times without an ack"


@dataclass
class _Delivery:
    report: SyncReport
    deadline: datetime
    deliveries: int


class InProcessReportStream:
    """A ReportStream held in memory: one lane, first delivery in publish order.

    `group` and `consumer` are accepted for port compatibility. Use it from one event loop.
    """

    def __init__(
        self,
        clock: Clock,
        *,
        visibility_timeout: timedelta = DEFAULT_VISIBILITY_TIMEOUT,
        max_deliveries: int = DEFAULT_MAX_DELIVERIES,
    ) -> None:
        self._clock = clock
        self._visibility_timeout = visibility_timeout
        self._max_deliveries = max_deliveries
        self._ready: deque[tuple[SyncReport, int]] = deque()  # report, deliveries so far
        self._in_flight: dict[str, _Delivery] = {}
        self._dead: list[DeadReport] = []
        self._wakeup = asyncio.Event()

    async def publish(self, report: SyncReport) -> None:
        self._ready.append((report, 0))
        self._wakeup.set()
        logger.info(
            "report published",
            extra={"correlation_id": report.correlation_id, "source": report.source},
        )

    async def consume(self, group: str, consumer: str, block_ms: int) -> SyncReport | None:  # noqa: ARG002
        loop = asyncio.get_running_loop()
        give_up_at = loop.time() + block_ms / 1000
        while True:
            self._reclaim_expired()
            if self._ready:
                report, seen = self._ready.popleft()
                deadline = self._clock.now() + self._visibility_timeout
                self._in_flight[report.id] = _Delivery(report, deadline, seen + 1)
                return report
            remaining = give_up_at - loop.time()
            if remaining <= 0:
                return None
            wait = min(remaining, self._seconds_until_deadline())
            self._wakeup.clear()
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=wait)
            except TimeoutError:
                continue

    async def ack(self, report: SyncReport) -> None:
        self._in_flight.pop(report.id, None)

    async def dead_letter(self, report: SyncReport, reason: str) -> None:
        delivery = self._in_flight.pop(report.id, None)
        if delivery is not None:
            self._give_up(delivery.report, trim(reason, MAX_REASON_LENGTH))

    async def list_dead_reports(self) -> list[DeadReport]:
        return list(self._dead)

    def _give_up(self, report: SyncReport, reason: str) -> None:
        self._dead.append(
            DeadReport(
                id=report.id,
                correlation_id=report.correlation_id,
                source=report.source,
                reason=reason,
                failed_at=self._clock.now(),
            )
        )
        logger.error(
            "report dead-lettered: %s",
            reason,
            extra={
                "correlation_id": report.correlation_id,
                "source": report.source,
                "reason": reason,
            },
        )

    def _reclaim_expired(self) -> None:
        now = self._clock.now()
        expired = [d for d in self._in_flight.values() if d.deadline <= now]
        again: list[tuple[SyncReport, int]] = []
        for delivery in expired:
            del self._in_flight[delivery.report.id]
            if delivery.deliveries >= self._max_deliveries:
                self._give_up(delivery.report, DELIVERIES_EXHAUSTED_REASON)
            else:
                again.append((delivery.report, delivery.deliveries))
        self._ready.extendleft(reversed(again))

    def _seconds_until_deadline(self) -> float:
        if not self._in_flight:
            return float("inf")
        soonest = min(d.deadline for d in self._in_flight.values())
        return max((soonest - self._clock.now()).total_seconds(), 0.0)
