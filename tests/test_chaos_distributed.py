"""Chaos tests: kill the processes at the worst moment and check nothing is lost or doubled.

Each case runs on the in-process backends always, and on Redis when CC_TEST_REDIS_URL is set
(the Redis case really expires visibility timeouts, so it takes a second or two).
"""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio

from command_center.core.errors import TransientError
from command_center.core.jobs import Job
from command_center.core.ports import JobQueue, SyncStateStore
from fakes import InMemoryEventStore
from fetch_support import until_fetching
from queue_support import POLICY, REDIS_URL_ENV, WINDOW, make_job
from worker_support import (
    BREAKER_FAILURES,
    COOL_DOWN,
    Backend,
    InMemorySyncStateStore,
    adapter_with,
    events,
    inprocess_backend,
    make_normalizer,
    make_report,
    make_worker,
    redis_backend,
)

BACKENDS = [
    pytest.param("inprocess", id="inprocess"),
    pytest.param(
        "redis",
        id="redis",
        marks=pytest.mark.skipif(
            not os.environ.get(REDIS_URL_ENV), reason=f"{REDIS_URL_ENV} is not set"
        ),
    ),
]
GROUP = "sync-workers"


@pytest_asyncio.fixture(params=BACKENDS)
async def backend(request: pytest.FixtureRequest) -> AsyncIterator[Backend]:
    factory = inprocess_backend if request.param == "inprocess" else redis_backend
    async for item in factory():
        yield item


class WorkerKilled(BaseException):  # like a SIGKILL: no `except Exception` sees it
    """Raised where a process would have died."""


class DiesOnAck:
    """A JobQueue whose ack kills the worker: the report went out but the job was never acked."""

    def __init__(self, inner: JobQueue) -> None:
        self._inner = inner

    async def publish(self, job: Job) -> None:
        await self._inner.publish(job)

    async def consume(self, group: str, consumer: str, block_ms: int) -> Job | None:
        return await self._inner.consume(group, consumer, block_ms)

    async def ack(self, job: Job) -> None:  # noqa: ARG002
        raise WorkerKilled

    async def fail(self, job: Job, reason: str) -> None:
        await self._inner.fail(job, reason)

    async def dead_letter(self, job: Job, reason: str) -> None:
        await self._inner.dead_letter(job, reason)

    async def list_dead_letters(self):  # type: ignore[no-untyped-def]  # noqa: ANN201
        return await self._inner.list_dead_letters()


class CrashesAfterReplace(InMemorySyncStateStore):
    """A state store whose first put kills the normalizer: the events were already replaced."""

    def __init__(self) -> None:
        super().__init__()
        self.crashed = False

    def put(self, state, *, user_id: str = "local") -> None:  # type: ignore[no-untyped-def]  # noqa: ANN001
        if not self.crashed:
            self.crashed = True
            raise WorkerKilled
        super().put(state, user_id=user_id)


async def drain_reports(
    backend: Backend, store: InMemoryEventStore, states: SyncStateStore
) -> None:
    normalizer = make_normalizer(backend.reports(), store, states)  # type: ignore[arg-type]
    while await normalizer.run_once():
        pass


def stored(store: InMemoryEventStore) -> list[str]:
    return [e.id for e in store.query(WINDOW)]


async def test_a_worker_killed_mid_fetch_has_its_job_redelivered_with_no_duplicate_events(
    backend: Backend,
) -> None:
    await backend.queue().publish(make_job("j1"))
    gate = asyncio.Event()  # never set: the first worker is stuck inside fetch
    doomed = adapter_with(events("a", "b"), gate=gate)
    first = asyncio.create_task(
        make_worker(
            doomed, backend.queue(), backend.reports(), backend.clock, consumer="w1"
        ).run_once()
    )
    await until_fetching(doomed)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    await backend.expire()
    survivor = adapter_with(events("a", "b"))
    queue = backend.queue()
    assert await make_worker(
        survivor, queue, backend.reports(), backend.clock, consumer="w2"
    ).run_once()

    store, states = InMemoryEventStore(), InMemorySyncStateStore()
    await drain_reports(backend, store, states)
    assert stored(store) == ["a", "b"]
    state = states.get("canvas")
    assert state is not None
    assert (state.status, state.message) == ("ok", "Synced 2 items")
    assert await queue.list_dead_letters() == []


async def test_a_worker_killed_after_reporting_but_before_the_ack_leaves_the_same_events(
    backend: Backend,
) -> None:
    await backend.queue().publish(make_job("j1"))
    dying = make_worker(
        adapter_with(events("a", "b")),
        DiesOnAck(backend.queue()),
        backend.reports(),
        backend.clock,
        consumer="w1",
    )
    with pytest.raises(WorkerKilled):
        await dying.run_once()

    await backend.expire()
    assert await make_worker(
        adapter_with(events("a", "b")),
        backend.queue(),
        backend.reports(),
        backend.clock,
        consumer="w2",
    ).run_once()

    store, states = InMemoryEventStore(), InMemorySyncStateStore()
    await drain_reports(backend, store, states)  # two reports for one job
    assert stored(store) == ["a", "b"]
    assert len(store.query(WINDOW)) == 2


async def test_a_normalizer_crash_after_replace_and_redelivery_leaves_identical_state(
    backend: Backend,
) -> None:
    reports = backend.reports()
    await reports.publish(make_report(items=events("a", "b")))

    reference_store, reference_states = InMemoryEventStore(), InMemorySyncStateStore()
    reference_reports = backend.reports()
    await reference_reports.publish(make_report("r-ref", items=events("a", "b")))
    await make_normalizer(reference_reports, reference_store, reference_states).run_once()

    store, states = InMemoryEventStore(), CrashesAfterReplace()
    crashing = make_normalizer(backend.reports(), store, states, "norm-1")
    while True:  # the first report to arrive is the one that crashes
        try:
            await crashing.run_once()
        except WorkerKilled:
            break
    assert stored(store) == ["a", "b"]  # replace had already happened
    assert states.get("canvas") is None

    await backend.expire()
    survivor = make_normalizer(backend.reports(), store, states, "norm-2")
    while await survivor.run_once():
        pass

    assert stored(store) == stored(reference_store)
    assert states.get("canvas") == reference_states.get("canvas")


async def test_a_poisoned_job_is_dead_lettered_after_the_last_attempt(backend: Backend) -> None:
    queue = backend.queue()
    await queue.publish(make_job("poison"))
    adapter = adapter_with(TransientError("always fails"))
    worker = make_worker(adapter, queue, backend.reports(), backend.clock)
    for _ in range(POLICY.max_attempts):
        assert await worker.run_once() is True
        await backend.let_retries_elapse()

    [dead] = await queue.list_dead_letters()
    assert (dead.job.id, dead.job.attempt, dead.reason) == (
        "poison",
        POLICY.max_attempts,
        "TransientError",
    )
    assert len(adapter.fetches) == POLICY.max_attempts
    assert await worker.run_once() is False


async def test_a_job_that_kills_every_worker_is_dead_lettered_by_the_visibility_timeout(
    backend: Backend,
) -> None:
    queue = backend.queue()
    await queue.publish(make_job("killer"))
    for n in range(POLICY.max_attempts):
        gate = asyncio.Event()
        stuck = adapter_with(events("a"), gate=gate)
        task = asyncio.create_task(
            make_worker(
                stuck, backend.queue(), backend.reports(), backend.clock, consumer=f"w{n}"
            ).run_once()
        )
        await until_fetching(stuck)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await backend.expire()

    assert await backend.queue().consume(GROUP, "next", 0) is None
    [dead] = await queue.list_dead_letters()
    assert (dead.job.id, dead.job.attempt) == ("killer", POLICY.max_attempts)


async def test_the_breaker_opens_after_n_failures_and_recovers_when_the_source_does(
    backend: Backend,
) -> None:
    queue = backend.queue()
    adapter = adapter_with(*[TransientError("down")] * BREAKER_FAILURES, events("a"))
    worker = make_worker(adapter, queue, backend.reports(), backend.clock)
    for n in range(BREAKER_FAILURES):
        await queue.publish(make_job(f"j{n}"))
        assert await worker.run_once() is True

    await queue.publish(make_job("waiting"))
    assert await worker.run_once() is False  # open: nothing is consumed, nothing is fetched
    assert len(adapter.fetches) == BREAKER_FAILURES

    backend.clock.advance(COOL_DOWN + timedelta(seconds=1))
    assert await worker.run_once() is True  # the half-open trial succeeds
    store, states = InMemoryEventStore(), InMemorySyncStateStore()
    await drain_reports(backend, store, states)
    assert stored(store) == ["a"]
    assert len(adapter.fetches) == BREAKER_FAILURES + 1
