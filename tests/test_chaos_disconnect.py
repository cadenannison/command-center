"""Chaos: disconnect a source while work for it is in flight; nothing of it may come back (0074).

Each case runs on the in-process backends always, and on Redis when CC_TEST_REDIS_URL is set.
"""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from command_center.core.jobs import Job
from command_center.core.ports import JobQueue
from distributed_support import TOKEN, DistributedRig, make_distributed_rig
from queue_support import REDIS_URL_ENV, WINDOW
from worker_support import (
    Backend,
    adapter_with,
    events,
    inprocess_backend,
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


def stored(rig: DistributedRig) -> list[str]:
    return [e.id for e in rig.events.query(WINDOW)]


async def drain(rig: DistributedRig) -> None:
    normalizer = rig.normalizer()
    while await normalizer.run_once():
        pass


FETCH_WAIT_SECONDS = 5.0  # a bound for a hang, not a delay: the loop below yields, it never sleeps


async def until_fetching(adapter: object, wait_seconds: float = FETCH_WAIT_SECONDS) -> None:
    """Return once a worker is inside `adapter.fetch`; fail the test if none gets there in time."""
    try:
        async with asyncio.timeout(wait_seconds):
            while adapter.in_flight == 0:  # type: ignore[attr-defined]  # noqa: ASYNC110
                await asyncio.sleep(0)
    except TimeoutError:
        pytest.fail(
            f"No worker started fetching within {wait_seconds:g} s: the job was never consumed, "
            "or the worker died before it called the adapter"
        )


async def connect_and_queue(rig: DistributedRig) -> None:
    await rig.settings.connect("canvas", TOKEN)
    await rig.sync.sync("canvas")  # what the route's background task does after a connect


async def test_a_disconnect_during_a_fetch_leaves_nothing_even_when_the_job_is_redelivered(
    backend: Backend,
) -> None:
    gate = asyncio.Event()
    adapter = adapter_with(events("a", "b"), gate=gate)
    rig = make_distributed_rig(backend, adapter)
    await connect_and_queue(rig)

    # The worker holds the job and is inside fetch when the user disconnects.
    dying = make_worker(
        adapter,
        DiesOnAck(backend.queue()),
        backend.reports(),
        backend.clock,
        secrets=rig.secrets,
        consumer="w1",
    )
    running = asyncio.create_task(dying.run_once())
    await until_fetching(adapter)
    await rig.settings.disconnect("canvas")
    gate.set()
    with pytest.raises(WorkerKilled):  # the report went out; the ack never happened
        await running

    await drain(rig)
    assert stored(rig) == []

    # The job comes back after the visibility timeout and is worked again.
    await backend.expire()
    survivor = make_worker(
        adapter_with(events("a", "b")),
        backend.queue(),
        backend.reports(),
        backend.clock,
        secrets=rig.secrets,
        consumer="w2",
    )
    assert await survivor.run_once() is True
    await drain(rig)

    assert stored(rig) == []
    assert rig.states.get("canvas") is None


async def test_a_report_delivered_twice_after_a_disconnect_leaves_the_store_empty(
    backend: Backend,
) -> None:
    adapter = adapter_with(events("a", "b"))
    rig = make_distributed_rig(backend, adapter)
    await connect_and_queue(rig)
    worker = rig.worker()
    assert await worker.run_once() is True  # the report is published, not yet applied

    await rig.settings.disconnect("canvas")
    duplicate = await backend.reports().consume("probe", "p", 0)  # the same report, taken twice
    assert duplicate is not None
    await backend.reports().publish(duplicate)

    await drain(rig)

    assert stored(rig) == []
    assert rig.states.get("canvas") is None


async def test_a_reconnect_after_the_chaos_syncs_again(backend: Backend) -> None:
    gate = asyncio.Event()
    adapter = adapter_with(events("a"), gate=gate)
    rig = make_distributed_rig(backend, adapter)
    await connect_and_queue(rig)
    running = asyncio.create_task(rig.worker().run_once())
    await until_fetching(adapter)
    await rig.settings.disconnect("canvas")
    gate.set()
    await running
    await drain(rig)
    assert stored(rig) == []

    await connect_and_queue(rig)  # the user connects again: a job with the new generation
    assert await rig.worker().run_once() is True
    await drain(rig)

    assert stored(rig) == ["a"]
    state = rig.states.get("canvas")
    assert state is not None
    assert state.status == "ok"


async def test_waiting_for_a_fetch_that_never_starts_fails_with_a_message_instead_of_hanging() -> (
    None
):
    idle = adapter_with(events("a"))  # nothing runs a worker against it
    with pytest.raises(pytest.fail.Exception, match=r"No worker started fetching within 0\.05 s"):
        await until_fetching(idle, wait_seconds=0.05)
