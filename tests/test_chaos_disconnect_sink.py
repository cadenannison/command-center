"""Chaos: disconnect while work is in flight, with the normalizer the deployed roles run (0075).

The same scenarios as test_chaos_disconnect.py, but the stores are the real SQL ones and the
normalizer has a ReportSink, as `workers/__main__._run_normalizer` builds it. In-process always,
Redis when CC_TEST_REDIS_URL is set.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio

from command_center.workers.normalizer import Normalizer
from distributed_support import TOKEN, DistributedRig, make_distributed_rig
from fake_adapter import FakeAdapter
from queue_support import REDIS_URL_ENV, WINDOW
from sink_support import Stores, open_engine, open_stores
from test_chaos_disconnect import DiesOnAck, WorkerKilled
from worker_support import (
    Backend,
    ClockSleep,
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


@pytest.fixture
def stores(tmp_path: Path) -> Iterator[Stores]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_stores(engine)


def make_rig(backend: Backend, adapter: FakeAdapter, stores: Stores) -> DistributedRig:
    return make_distributed_rig(
        backend,
        adapter,
        events=stores.events,
        states=stores.states,
        generations=stores.generations,
    )


def sink_normalizer(backend: Backend, stores: Stores, consumer: str = "norm-1") -> Normalizer:
    return Normalizer(
        backend.reports(),
        stores.events,
        stores.states,
        generations=stores.generations,
        sink=stores.sink,
        consumer=consumer,
        block_ms=0,
        sleep=ClockSleep(backend.clock),
    )


def stored(stores: Stores) -> list[str]:
    return [e.id for e in stores.events.query(WINDOW)]


async def drain(backend: Backend, stores: Stores) -> None:
    normalizer = sink_normalizer(backend, stores)
    while await normalizer.run_once():
        pass


async def until_fetching(adapter: object) -> None:
    async with asyncio.timeout(10):  # a test that cannot get there fails instead of hanging
        while adapter.in_flight == 0:  # type: ignore[attr-defined]  # noqa: ASYNC110
            await asyncio.sleep(0)


async def connect_and_queue(rig: DistributedRig) -> None:
    await rig.settings.connect("canvas", TOKEN)
    await rig.sync.sync("canvas")  # what the route's background task does after a connect


async def test_a_disconnect_during_a_fetch_leaves_nothing_even_when_the_job_is_redelivered(
    backend: Backend, stores: Stores
) -> None:
    gate = asyncio.Event()
    adapter = adapter_with(events("a", "b"), gate=gate)
    rig = make_rig(backend, adapter, stores)
    await connect_and_queue(rig)

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

    await drain(backend, stores)
    assert stored(stores) == []

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
    await drain(backend, stores)

    assert stored(stores) == []
    assert stores.states.get("canvas") is None


async def test_a_report_delivered_twice_after_a_disconnect_leaves_the_store_empty(
    backend: Backend, stores: Stores
) -> None:
    adapter = adapter_with(events("a", "b"))
    rig = make_rig(backend, adapter, stores)
    await connect_and_queue(rig)
    assert await rig.worker().run_once() is True  # published, not yet applied

    await rig.settings.disconnect("canvas")
    duplicate = await backend.reports().consume("probe", "p", 0)
    assert duplicate is not None
    await backend.reports().publish(duplicate)

    await drain(backend, stores)

    assert stored(stores) == []
    assert stores.states.get("canvas") is None


async def test_a_reconnect_after_the_chaos_syncs_again_and_a_late_duplicate_cannot_undo_it(
    backend: Backend, stores: Stores
) -> None:
    gate = asyncio.Event()
    adapter = adapter_with(events("a"), gate=gate)
    rig = make_rig(backend, adapter, stores)
    await connect_and_queue(rig)
    running = asyncio.create_task(rig.worker().run_once())
    await until_fetching(adapter)
    await rig.settings.disconnect("canvas")
    gate.set()
    await running
    # The generation-0 report is still in the stream: the user reconnects before it is applied.
    await connect_and_queue(rig)
    assert await rig.worker().run_once() is True

    await drain(backend, stores)

    assert stored(stores) == ["a"]  # the new connection's data; the old report was dropped
    state = stores.states.get("canvas")
    assert state is not None
    assert state.status == "ok"
