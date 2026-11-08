"""Shared pieces for the JobQueue contract suite: job builder, seeded Rng, the two backends."""

import asyncio
import os
import random
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from command_center.adapters.inprocess_queue import InProcessQueue
from command_center.core.jobs import Job
from command_center.core.ports import JobQueue
from command_center.core.resilience import RetryPolicy
from command_center.core.windows import TimeWindow
from fakes import FakeClock

REDIS_URL_ENV = "CC_TEST_REDIS_URL"
START = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
POLICY = RetryPolicy(
    max_attempts=3, base_delay=timedelta(seconds=2), factor=2.0, cap=timedelta(seconds=10)
)
VISIBILITY = timedelta(seconds=1)
WINDOW = TimeWindow(start=START, end=START + timedelta(days=1))


class SeededRng:
    """An Rng backed by a seeded generator."""

    def __init__(self, seed: int = 7) -> None:
        self._random = random.Random(seed)  # noqa: S311

    def random(self) -> float:
        return self._random.random()


def make_job(job_id: str, source: str = "canvas", kind: str = "sync") -> Job:
    return Job(id=job_id, kind=kind, source=source, window=WINDOW, correlation_id=f"corr-{job_id}")


@dataclass
class Harness:
    """A queue under test plus the way to let time pass for its backend."""

    queue: JobQueue
    clock: FakeClock
    real_sleep_seconds: float = 0.0

    async def advance(self, delta: timedelta) -> None:
        """Let retry delays elapse (the queue's Clock moves)."""
        self.clock.advance(delta)

    async def settle(self) -> None:
        """Give a consumer started in the background time to reach its blocking read."""
        await asyncio.sleep(0.2 if self.real_sleep_seconds else 0)

    async def expire_visibility(self) -> None:
        """Let the visibility timeout elapse: the Clock moves, and Redis also needs real time."""
        self.clock.advance(VISIBILITY * 2)
        if self.real_sleep_seconds:
            await asyncio.sleep(self.real_sleep_seconds)


async def inprocess_harness() -> AsyncIterator[Harness]:
    clock = FakeClock(START)
    queue = InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
    yield Harness(queue, clock)


async def redis_harness() -> AsyncIterator[Harness]:
    from redis.asyncio import Redis  # noqa: PLC0415

    from command_center.adapters.queue_redis import RedisStreamsQueue  # noqa: PLC0415

    clock = FakeClock(START)
    prefix = f"cc-test-{uuid.uuid4().hex}"
    queue = RedisStreamsQueue.from_url(
        os.environ[REDIS_URL_ENV],
        clock,
        SeededRng(),
        prefix=prefix,
        policy=POLICY,
        visibility_timeout=VISIBILITY,
    )
    try:
        yield Harness(queue, clock, real_sleep_seconds=VISIBILITY.total_seconds() * 1.2)
    finally:
        await queue.aclose()
        cleaner = Redis.from_url(os.environ[REDIS_URL_ENV])  # pyright: ignore[reportUnknownMemberType]
        try:
            await cleaner.delete(
                f"{{{prefix}}}:jobs", f"{{{prefix}}}:jobs:delayed", f"{{{prefix}}}:jobs:dead"
            )
        finally:
            await cleaner.aclose()
