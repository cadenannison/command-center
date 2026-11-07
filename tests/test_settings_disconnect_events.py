"""Disconnecting a source also deletes its stored events."""

import asyncio
import threading
from collections.abc import Mapping
from datetime import timedelta

from builders import NOW, make_event
from command_center.core.schema import Event
from command_center.core.windows import TimeWindow
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from fake_adapter import FakeAdapter, RecordingSleep, UnavailableSecretStore
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

EVERYTHING = TimeWindow(start=NOW - timedelta(days=400), end=NOW + timedelta(days=400))
TOKEN = {"token": "fake-token-12345678"}


class ThreadRecordingDeleteStore(InMemoryEventStore):
    """An event store that notes the thread of each delete_source."""

    def __init__(self) -> None:
        super().__init__()
        self.delete_threads: list[int] = []

    def delete_source(self, source: str, *, user_id: str = "local") -> int:
        self.delete_threads.append(threading.get_ident())
        return super().delete_source(source, user_id=user_id)


def make_services(
    events: InMemoryEventStore,
    adapters: list[FakeAdapter] | None = None,
    secrets: InMemorySecretStore | UnavailableSecretStore | None = None,
) -> tuple[SettingsService, SyncService]:
    chosen = adapters or [FakeAdapter()]
    store = secrets if secrets is not None else InMemorySecretStore()
    by_name = {adapter.name: adapter for adapter in chosen}
    sync = SyncService(by_name, store, events, FakeClock(NOW), sleep=RecordingSleep())
    return SettingsService(by_name, store, sync), sync


def stored_ids(events: InMemoryEventStore) -> list[str]:
    return [event.id for event in events.query(EVERYTHING)]


async def test_disconnect_deletes_the_stored_events_of_the_source() -> None:
    events = InMemoryEventStore()
    events.upsert([make_event(id="dated", start=NOW), make_event(id="undated")])
    settings, _ = make_services(events)

    await settings.disconnect("canvas")

    assert events.delete_source("canvas") == 0


async def test_disconnect_leaves_the_events_of_other_sources() -> None:
    events = InMemoryEventStore()
    events.upsert([make_event(id="mail", source="gmail", start=NOW)])
    settings, _ = make_services(events, [FakeAdapter("canvas"), FakeAdapter("gmail")])

    await settings.disconnect("canvas")

    assert stored_ids(events) == ["mail"]


async def test_disconnect_deletes_events_off_the_event_loop_thread() -> None:
    events = ThreadRecordingDeleteStore()
    settings, _ = make_services(events)

    await settings.disconnect("canvas")

    assert events.delete_threads
    assert threading.get_ident() not in events.delete_threads


async def test_disconnect_keeps_the_events_when_the_secret_store_is_unavailable() -> None:
    events = InMemoryEventStore()
    events.upsert([make_event(id="a", start=NOW)])
    settings, _ = make_services(events, secrets=UnavailableSecretStore())

    await settings.disconnect("canvas")

    assert stored_ids(events) == ["a"]


class SignallingAdapter(FakeAdapter):
    """A FakeAdapter that says when its fetch has begun, so a test knows the sync is past setup."""

    def __init__(self, *, gate: asyncio.Event) -> None:
        super().__init__(script=[[make_event(id="a", start=NOW)]], gate=gate)
        self.fetching = asyncio.Event()

    async def fetch(self, creds: Mapping[str, str], window: TimeWindow) -> list[Event]:
        self.fetching.set()
        return await super().fetch(creds, window)


async def test_a_sync_that_finishes_after_the_disconnect_does_not_bring_the_events_back() -> None:
    events = InMemoryEventStore()
    gate = asyncio.Event()
    adapter = SignallingAdapter(gate=gate)
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", TOKEN["token"])
    settings, sync = make_services(events, [adapter], secrets)

    running = asyncio.create_task(sync.sync("canvas"))
    await adapter.fetching.wait()
    await settings.disconnect("canvas")
    gate.set()
    await running

    assert stored_ids(events) == []
