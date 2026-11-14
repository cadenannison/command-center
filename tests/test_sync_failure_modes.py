"""A cancelled sync resets its state; sync_all isolates one source's unexpected error (0406)."""

import asyncio

import pytest

from builders import NOW, make_event
from command_center.services.sync import INTERRUPTED_MESSAGE, UNEXPECTED_MESSAGE, SyncService
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore
from worker_support import InMemorySyncStateStore


def make(*adapters: FakeAdapter) -> tuple[SyncService, InMemorySyncStateStore]:
    secrets = InMemorySecretStore()
    for adapter in adapters:
        secrets.set(adapter.name, "token", "fake-token-12345678")
    states = InMemorySyncStateStore()
    service = SyncService(
        {a.name: a for a in adapters},
        secrets,
        InMemoryEventStore(),
        FakeClock(NOW),
        sleep=RecordingSleep(),
        states=states,
    )
    return service, states


async def test_cancelled_sync_leaves_a_state_that_is_not_syncing() -> None:
    gate = asyncio.Event()
    adapter = FakeAdapter(gate=gate)
    service, states = make(adapter)

    task = asyncio.create_task(service.sync("canvas"))
    while not adapter.in_flight:  # noqa: ASYNC110
        await asyncio.sleep(0)
    syncing = states.get("canvas")
    assert syncing is not None
    assert syncing.status == "syncing"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    stored = states.get("canvas")
    assert stored is not None
    assert stored.status == "error"
    assert stored.message == INTERRUPTED_MESSAGE


async def test_sync_all_returns_a_state_per_source_when_one_adapter_raises() -> None:
    adapters = [
        FakeAdapter("canvas", script=[[make_event(id="a", start=NOW)]]),
        FakeAdapter("google", script=[RuntimeError("boom with detail")]),
        FakeAdapter("ical", script=[[make_event(id="b", source="ical", start=NOW)]]),
    ]
    service, _ = make(*adapters)

    results = await service.sync_all()

    by_source = {s.source: s for s in results}
    assert set(by_source) == {"canvas", "google", "ical"}
    assert by_source["google"].status == "error"
    assert by_source["google"].message == UNEXPECTED_MESSAGE
    assert by_source["canvas"].status == "ok"
    assert by_source["ical"].status == "ok"


async def test_cancelled_sync_all_propagates_the_cancellation() -> None:
    gate = asyncio.Event()
    adapter = FakeAdapter(gate=gate)
    service, _ = make(adapter)

    task = asyncio.create_task(service.sync_all())
    while not adapter.in_flight:  # noqa: ASYNC110
        await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    final = service.state("canvas")
    assert final is not None
    assert final.status == "error"
