"""In-process JobQueue for single-process mode and tests. Decisions: 0047, 0048, 0049."""

import asyncio
import heapq
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from command_center.adapters.json_log import job_fields
from command_center.core.jobs import MAX_REASON_LENGTH, VISIBILITY_TIMEOUT_REASON, DeadLetter, Job
from command_center.core.ports import Clock, Rng
from command_center.core.redact import trim
from command_center.core.resilience import (
    DEFAULT_RETRY_POLICY,
    DEFAULT_VISIBILITY_TIMEOUT,
    RetryPolicy,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Delivery:
    job: Job
    deadline: datetime


class InProcessQueue:
    """A JobQueue held in memory: one lane, FIFO in publish order, state lost on exit.

    `group` and `consumer` are accepted for port compatibility; every consumer shares the one lane.
    Use it from a single event loop.
    """

    def __init__(
        self,
        clock: Clock,
        rng: Rng,
        *,
        policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        visibility_timeout: timedelta = DEFAULT_VISIBILITY_TIMEOUT,
    ) -> None:
        self._clock = clock
        self._rng = rng
        self._policy = policy
        self._visibility_timeout = visibility_timeout
        self._ready: deque[Job] = deque()
        self._delayed: list[tuple[datetime, int, Job]] = []
        self._in_flight: dict[str, _Delivery] = {}
        self._dead: list[DeadLetter] = []
        self._sequence = 0
        self._wakeup = asyncio.Event()

    async def publish(self, job: Job) -> None:
        self._ready.append(job)
        self._wakeup.set()
        logger.info("job published", extra=job_fields(job))

    async def consume(self, group: str, consumer: str, block_ms: int) -> Job | None:  # noqa: ARG002
        loop = asyncio.get_running_loop()
        give_up_at = loop.time() + block_ms / 1000
        while True:
            self._reclaim_expired()
            self._promote_due()
            if self._ready:
                job = self._ready.popleft()
                deadline = self._clock.now() + self._visibility_timeout
                self._in_flight[job.id] = _Delivery(job, deadline)
                return job
            remaining = give_up_at - loop.time()
            if remaining <= 0:
                return None
            wait = min(remaining, self._seconds_until_next_event())
            self._wakeup.clear()
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=wait)
            except TimeoutError:
                continue

    async def ack(self, job: Job) -> None:
        # A late ack from a superseded delivery still completes the job: the work was done.
        if self._in_flight.pop(job.id, None) is None:
            logger.debug("ack ignored: job not in flight", extra=job_fields(job))

    async def fail(self, job: Job, reason: str) -> None:
        delivery = self._in_flight.pop(job.id, None)
        if delivery is None:
            logger.debug("fail ignored: job not in flight", extra=job_fields(job))
            return
        held = delivery.job
        reason = trim(reason, MAX_REASON_LENGTH)
        if self._policy.exhausted(held.attempt):
            self._dead_letter(held, reason)
            return
        delay = self._policy.delay(held.attempt, self._rng)
        self._push_delayed(held.next_attempt(), self._clock.now() + delay)
        logger.warning(
            "job failed, retry in %.1fs: %s",
            delay.total_seconds(),
            reason,
            extra={**job_fields(held), "delay_seconds": delay.total_seconds(), "reason": reason},
        )

    async def dead_letter(self, job: Job, reason: str) -> None:
        delivery = self._in_flight.pop(job.id, None)
        if delivery is None:
            logger.debug("dead_letter ignored: job not in flight", extra=job_fields(job))
            return
        self._dead_letter(delivery.job, trim(reason, MAX_REASON_LENGTH))

    async def list_dead_letters(self) -> list[DeadLetter]:
        return list(self._dead)

    def _dead_letter(self, job: Job, reason: str) -> None:
        self._dead.append(DeadLetter(job=job, reason=reason, failed_at=self._clock.now()))
        logger.error("job dead-lettered: %s", reason, extra={**job_fields(job), "reason": reason})

    def _push_delayed(self, job: Job, ready_at: datetime) -> None:
        self._sequence += 1
        heapq.heappush(self._delayed, (ready_at, self._sequence, job))
        self._wakeup.set()

    def _promote_due(self) -> None:
        now = self._clock.now()
        while self._delayed and self._delayed[0][0] <= now:
            self._ready.append(heapq.heappop(self._delayed)[2])

    def _reclaim_expired(self) -> None:
        # In-flight entries are in delivery order, so redelivery keeps the original order and
        # goes ahead of newer jobs.
        now = self._clock.now()
        expired = [d for d in self._in_flight.values() if d.deadline <= now]
        redeliver: list[Job] = []
        for delivery in expired:
            del self._in_flight[delivery.job.id]
            job = delivery.job
            if self._policy.exhausted(job.attempt):
                self._dead_letter(job, VISIBILITY_TIMEOUT_REASON)
                continue
            redeliver.append(job.next_attempt())
            logger.warning(
                "job redelivered after visibility timeout",
                extra={**job_fields(job), "reason": "visibility timeout"},
            )
        self._ready.extendleft(reversed(redeliver))

    def _seconds_until_next_event(self) -> float:
        now = self._clock.now()
        times = [d.deadline for d in self._in_flight.values()]
        if self._delayed:
            times.append(self._delayed[0][0])
        if not times:
            return float("inf")
        return max((min(times) - now).total_seconds(), 0.0)
