"""Shared pieces for the worker, normalizer and chaos tests: builders, rigs, an in-memory store."""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta

from builders import make_event
from command_center.adapters.inprocess_queue import InProcessQueue
from command_center.adapters.inprocess_reports import InProcessReportStream
from command_center.core.jobs import SyncReport
from command_center.core.ports import JobQueue, ReportStream
from command_center.core.resilience import CircuitBreaker
from command_center.core.schema import Event
from command_center.core.sync_state import SyncState
from command_center.workers.normalizer import Normalizer
from command_center.workers.sync_worker import SyncWorker
from fake_adapter import FakeAdapter, FetchStep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore
from queue_support import POLICY, REDIS_URL_ENV, START, WINDOW, SeededRng

CREDS = {"token": "fake-token-1234"}
VISIBILITY = timedelta(seconds=1)
BREAKER_FAILURES = 3
COOL_DOWN = timedelta(seconds=30)
LONG_ENOUGH = timedelta(minutes=10)  # beyond any retry delay (the policy cap is 10 s)


class SequentialIds:
    """An IdSource that counts, so ids are reproducible."""

    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"id-{self._n}"


class InMemorySyncStateStore:
    """SyncStateStore in a dict; the SQLite one runs the same suite in test_sync_state_store."""

    def __init__(self) -> None:
        self.states: dict[tuple[str, str], SyncState] = {}

    def put(self, state: SyncState, *, user_id: str = "local") -> None:
        self.states[(user_id, state.source)] = state

    def get(self, source: str, *, user_id: str = "local") -> SyncState | None:
        return self.states.get((user_id, source))

    def delete(self, source: str, *, user_id: str = "local") -> None:
        self.states.pop((user_id, source), None)


def events(*ids: str, source: str = "canvas") -> list[Event]:
    """Events that fall in the test window (start inside it)."""
    return [make_event(id=i, source=source, title=f"Item {i}", start=START) for i in ids]


def make_report(  # noqa: PLR0913
    report_id: str = "r1",
    *,
    status: str = "ok",
    message: str = "",
    items: Sequence[Event] = (),
    source: str = "canvas",
    at_offset: timedelta = timedelta(0),
) -> SyncReport:
    return SyncReport.model_validate(
        {
            "id": report_id,
            "correlation_id": f"corr-{report_id}",
            "source": source,
            "window": WINDOW,
            "status": status,
            "message": message,
            "at": START + at_offset,
            "events": tuple(items),
        }
    )


@dataclass
class Backend:
    """Where jobs and reports live. `expire()` lets visibility timeouts elapse for the backend.

    A second `queue()` models a second process: in-process it is the same object, in Redis a
    new client that did not take the delivery (so it holds no entry ids of the dead worker).
    """

    clock: FakeClock
    make_queue: Callable[[], JobQueue]
    make_reports: Callable[[], ReportStream]
    real_sleep_seconds: float = 0.0

    def queue(self) -> JobQueue:
        return self.make_queue()

    def reports(self) -> ReportStream:
        return self.make_reports()

    async def expire(self) -> None:
        self.clock.advance(VISIBILITY * 2)
        if self.real_sleep_seconds:
            await asyncio.sleep(self.real_sleep_seconds)

    async def let_retries_elapse(self) -> None:
        self.clock.advance(LONG_ENOUGH)


async def inprocess_backend() -> AsyncIterator[Backend]:
    clock = FakeClock(START)
    queue = InProcessQueue(clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY)
    reports = InProcessReportStream(clock, visibility_timeout=VISIBILITY, max_deliveries=3)
    yield Backend(clock, lambda: queue, lambda: reports)


async def redis_backend() -> AsyncIterator[Backend]:
    from redis.asyncio import Redis  # noqa: PLC0415

    from command_center.adapters.queue_redis import (  # noqa: PLC0415
        RedisReportStream,
        RedisStreamsQueue,
    )

    clock = FakeClock(START)
    prefix = f"cc-chaos-{uuid.uuid4().hex}"
    url = os.environ[REDIS_URL_ENV]
    opened: list[RedisStreamsQueue | RedisReportStream] = []

    def make_queue() -> JobQueue:
        queue = RedisStreamsQueue.from_url(
            url, clock, SeededRng(), prefix=prefix, policy=POLICY, visibility_timeout=VISIBILITY
        )
        opened.append(queue)
        return queue

    def make_reports() -> ReportStream:
        stream = RedisReportStream.from_url(
            url, clock, prefix=prefix, visibility_timeout=VISIBILITY, max_deliveries=3
        )
        opened.append(stream)
        return stream

    try:
        yield Backend(
            clock, make_queue, make_reports, real_sleep_seconds=VISIBILITY.total_seconds() * 1.2
        )
    finally:
        for item in opened:
            await item.aclose()
        cleaner = Redis.from_url(url)  # pyright: ignore[reportUnknownMemberType]
        try:
            await cleaner.delete(
                f"{{{prefix}}}:jobs",
                f"{{{prefix}}}:jobs:delayed",
                f"{{{prefix}}}:jobs:dead",
                f"{{{prefix}}}:reports",
                f"{{{prefix}}}:reports:dead",
            )
        finally:
            await cleaner.aclose()


class ClockSleep:
    """Stands in for asyncio.sleep: time passes on the FakeClock, nothing really waits."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.calls = 0

    async def __call__(self, seconds: float) -> None:
        self.calls += 1
        self._clock.advance(timedelta(seconds=seconds))


def make_worker(  # noqa: PLR0913
    adapter: FakeAdapter,
    queue: JobQueue,
    reports: ReportStream,
    clock: FakeClock,
    *,
    secrets: InMemorySecretStore | None = None,
    consumer: str = "canvas-1",
    ids: SequentialIds | None = None,
) -> SyncWorker:
    if secrets is None:
        secrets = InMemorySecretStore()
        secrets.set(adapter.name, "token", CREDS["token"])
    return SyncWorker(
        adapter,
        secrets,
        queue,
        reports,
        CircuitBreaker(BREAKER_FAILURES, COOL_DOWN, clock),
        clock,
        ids or SequentialIds(),
        POLICY,
        consumer=consumer,
        block_ms=0,
        poll_seconds=1.0,
        sleep=ClockSleep(clock),
    )


def make_normalizer(
    reports: ReportStream,
    store: InMemoryEventStore,
    states: InMemorySyncStateStore,
    consumer: str = "norm-1",
) -> Normalizer:
    return Normalizer(
        reports, store, states, consumer=consumer, block_ms=0, sleep=ClockSleep(FakeClock(START))
    )


def adapter_with(*script: FetchStep, gate: asyncio.Event | None = None) -> FakeAdapter:
    return FakeAdapter("canvas", script=script, gate=gate)
