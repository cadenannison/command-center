"""SyncService replaces a source's events in the sync window, and only after a full fetch."""

import asyncio
import threading
from collections.abc import Sequence
from datetime import timedelta

import pytest

from builders import NOW, make_event
from command_center.core.errors import AuthExpired, FatalError, TransientError
from command_center.core.schema import Event
from command_center.core.windows import TimeWindow
from command_center.services.sync import SyncService
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

EVERYTHING = TimeWindow(start=NOW - timedelta(days=400), end=NOW + timedelta(days=400))
FAR_FUTURE = NOW + timedelta(days=100)  # beyond the 60-day sync horizon


class ThreadRecordingReplaceStore(InMemoryEventStore):
    """An event store that notes the thread and window of each replace."""

    def __init__(self) -> None:
        super().__init__()
        self.replace_threads: list[int] = []
        self.replace_windows: list[TimeWindow] = []

    def replace(
        self,
        source: str,
        window: TimeWindow,
        events: Sequence[Event],
        *,
        user_id: str = "local",
    ) -> int:
        self.replace_threads.append(threading.get_ident())
        self.replace_windows.append(window)
        return super().replace(source, window, events, user_id=user_id)


def make_service(adapters: list[FakeAdapter], events: InMemoryEventStore) -> SyncService:
    secrets = InMemorySecretStore()
    for adapter in adapters:
        secrets.set(adapter.name, "token", "fake-token-12345678")
    return SyncService(
        {adapter.name: adapter for adapter in adapters},
        secrets,
        events,
        FakeClock(NOW),
        sleep=RecordingSleep(),
    )


def stored_ids(events: InMemoryEventStore) -> list[str]:
    return [event.id for event in events.query(EVERYTHING)]


async def test_an_event_removed_at_the_source_disappears_on_the_next_sync() -> None:
    events = InMemoryEventStore()
    first = [make_event(id="a", start=NOW), make_event(id="b", start=NOW)]
    second = [make_event(id="a", start=NOW)]
    service = make_service([FakeAdapter(script=[first, second])], events)

    await service.sync("canvas")
    await service.sync("canvas")

    assert stored_ids(events) == ["a"]


async def test_a_moved_event_is_updated_by_the_next_sync() -> None:
    events = InMemoryEventStore()
    moved = make_event(id="a", start=NOW + timedelta(days=3), title="new")
    service = make_service(
        [FakeAdapter(script=[[make_event(id="a", start=NOW, title="old")], [moved]])], events
    )

    await service.sync("canvas")
    await service.sync("canvas")

    (event,) = events.query(EVERYTHING)
    assert (event.title, event.start) == ("new", NOW + timedelta(days=3))


async def test_replace_gets_the_sync_window_on_a_worker_thread() -> None:
    events = ThreadRecordingReplaceStore()
    adapter = FakeAdapter(script=[[make_event(id="a", start=NOW)]])

    await make_service([adapter], events).sync("canvas")

    (_, window) = adapter.fetches[0]
    assert events.replace_windows == [window]
    assert events.replace_threads
    assert threading.get_ident() not in events.replace_threads


async def test_events_outside_the_sync_window_are_not_pruned() -> None:
    events = InMemoryEventStore()
    events.upsert([make_event(id="far", start=FAR_FUTURE)])

    await make_service([FakeAdapter(script=[[make_event(id="a", start=NOW)]])], events).sync(
        "canvas"
    )

    assert stored_ids(events) == ["a", "far"]


async def test_syncing_one_source_leaves_the_events_of_another() -> None:
    events = InMemoryEventStore()
    events.upsert([make_event(id="mail", source="gmail", start=NOW)])

    await make_service([FakeAdapter("canvas"), FakeAdapter("gmail")], events).sync("canvas")

    assert stored_ids(events) == ["mail"]


async def test_the_synced_count_is_the_number_of_events_written() -> None:
    events = InMemoryEventStore()
    fetched = [make_event(id="a", start=NOW), make_event(id="b", start=NOW)]

    state = await make_service([FakeAdapter(script=[fetched])], events).sync("canvas")

    assert state.message == "Synced 2 items"


async def test_a_fatal_failure_keeps_the_old_events() -> None:
    events = InMemoryEventStore()
    adapter = FakeAdapter(script=[[make_event(id="a", start=NOW)], FatalError("broken")])
    service = make_service([adapter], events)

    await service.sync("canvas")
    state = await service.sync("canvas")

    assert (state.status, stored_ids(events)) == ("error", ["a"])


async def test_a_transient_failure_that_gives_up_keeps_the_old_events() -> None:
    events = InMemoryEventStore()
    adapter = FakeAdapter(script=[[make_event(id="a", start=NOW)], TransientError("timeout")])
    service = make_service([adapter], events)

    await service.sync("canvas")
    state = await service.sync("canvas")

    assert (state.status, stored_ids(events)) == ("error", ["a"])


async def test_rejected_credentials_keep_the_old_events() -> None:
    events = InMemoryEventStore()
    adapter = FakeAdapter(script=[[make_event(id="a", start=NOW)], AuthExpired("401")])
    service = make_service([adapter], events)

    await service.sync("canvas")
    state = await service.sync("canvas")

    assert (state.status, stored_ids(events)) == ("reconnect", ["a"])


async def test_a_source_with_no_credentials_keeps_its_events() -> None:
    events = InMemoryEventStore()
    events.upsert([make_event(id="a", start=NOW)])
    service = SyncService(
        {"canvas": FakeAdapter()},
        InMemorySecretStore(),
        events,
        FakeClock(NOW),
        sleep=RecordingSleep(),
    )

    state = await service.sync("canvas")

    assert (state.status, stored_ids(events)) == ("reconnect", ["a"])


async def test_a_sync_that_is_forgotten_while_it_runs_leaves_no_events() -> None:
    events = InMemoryEventStore()
    gate = asyncio.Event()
    adapter = FakeAdapter(script=[[make_event(id="a", start=NOW)]], gate=gate)
    service = make_service([adapter], events)

    running = asyncio.create_task(service.sync("canvas"))
    await asyncio.sleep(0)
    service.forget("canvas")
    gate.set()
    await running

    assert stored_ids(events) == []


class BrokenStore(InMemoryEventStore):
    """An event store whose replace and delete_source both fail, with different messages."""

    def replace(
        self,
        source: str,  # noqa: ARG002
        window: TimeWindow,  # noqa: ARG002
        events: Sequence[Event],  # noqa: ARG002
        *,
        user_id: str = "local",  # noqa: ARG002
    ) -> int:
        msg = "replace failed"
        raise RuntimeError(msg)

    def delete_source(self, source: str, *, user_id: str = "local") -> int:  # noqa: ARG002
        msg = "cleanup failed"
        raise RuntimeError(msg)


async def test_a_failed_cleanup_does_not_hide_the_sync_failure() -> None:
    gate = asyncio.Event()
    adapter = FakeAdapter(script=[[make_event(id="a", start=NOW)]], gate=gate)
    service = make_service([adapter], BrokenStore())

    running = asyncio.create_task(service.sync("canvas"))
    await asyncio.sleep(0.01)
    service.forget("canvas")
    gate.set()

    with pytest.raises(RuntimeError, match="replace failed"):
        await running
