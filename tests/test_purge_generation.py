"""`purge` bumps the generation again: a sync queued after `cancel` is dropped (decision 0086)."""

from collections.abc import AsyncIterator

import pytest_asyncio

from distributed_support import TOKEN, DistributedRig, make_distributed_rig
from fake_adapter import FakeAdapter
from queue_support import WINDOW
from worker_support import Backend, events, inprocess_backend


@pytest_asyncio.fixture
async def backend() -> AsyncIterator[Backend]:
    async for item in inprocess_backend():
        yield item


def make_rig(backend: Backend) -> DistributedRig:
    return make_distributed_rig(backend, FakeAdapter("canvas", script=[events("a", "b")]))


async def test_purge_bumps_the_generation_a_second_time(backend: Backend) -> None:
    rig = make_rig(backend)
    await rig.settings.connect("canvas", TOKEN)
    await rig.sync.cancel("canvas")
    assert rig.generations.current("canvas") == 1

    await rig.sync.purge("canvas")

    assert rig.generations.current("canvas") == 2


async def test_a_sync_queued_between_the_cancel_and_the_purge_is_dropped(backend: Backend) -> None:
    rig = make_rig(backend)
    await rig.settings.connect("canvas", TOKEN)
    await rig.sync.cancel("canvas")
    await rig.sync.sync("canvas")  # a scheduled round or POST /v1/sync, stamped with generation 1
    while await rig.worker().run_once():
        pass  # the worker still has the credentials and fetches

    await rig.sync.purge("canvas")
    while await rig.normalizer().run_once():
        pass

    assert [e.id for e in rig.events.query(WINDOW)] == []
    assert rig.states.get("canvas") is None
