"""SyncService writes each state through to the shared SyncStateStore and reads it back (0074)."""

import asyncio

import pytest

from builders import NOW, make_event
from command_center.core.errors import TransientError
from command_center.core.sync_state import SyncState
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore
from worker_support import InMemorySyncStateStore

TOKEN = {"token": "fake-token-12345678"}


class BrokenStateStore(InMemorySyncStateStore):
    """A state store whose database is unreachable."""

    def put(self, state: SyncState, *, user_id: str = "local") -> None:  # noqa: ARG002
        msg = "postgres://user:fake-pw@db down"
        raise ConnectionError(msg)

    def delete(self, source: str, *, user_id: str = "local") -> None:  # noqa: ARG002
        msg = "postgres://user:fake-pw@db down"
        raise ConnectionError(msg)


def make(
    adapter: FakeAdapter,
    states: InMemorySyncStateStore | None = None,
    events: InMemoryEventStore | None = None,
    secrets: InMemorySecretStore | None = None,
) -> tuple[SyncService, InMemorySyncStateStore, InMemoryEventStore, InMemorySecretStore]:
    states = states if states is not None else InMemorySyncStateStore()
    events = events if events is not None else InMemoryEventStore()
    secrets = secrets if secrets is not None else InMemorySecretStore()
    secrets.set(adapter.name, "token", TOKEN["token"])
    service = SyncService(
        {adapter.name: adapter},
        secrets,
        events,
        FakeClock(NOW),
        sleep=RecordingSleep(),
        states=states,
    )
    return service, states, events, secrets


async def test_a_finished_sync_is_written_to_the_store() -> None:
    service, states, _, _ = make(FakeAdapter(script=[[make_event(id="a", start=NOW)]]))

    await service.sync("canvas")

    stored = states.get("canvas")
    assert stored is not None
    assert (stored.status, stored.message, stored.at) == ("ok", "Synced 1 items", NOW)


async def test_a_failed_sync_is_written_too() -> None:
    service, states, _, secrets = make(FakeAdapter())
    secrets.delete("canvas")

    await service.sync("canvas")

    stored = states.get("canvas")
    assert stored is not None
    assert stored.status == "reconnect"


async def test_syncing_is_written_before_the_fetch_finishes() -> None:
    gate = asyncio.Event()
    service, states, _, _ = make(FakeAdapter(gate=gate))

    task = asyncio.create_task(service.sync("canvas"))
    while (stored := states.get("canvas")) is None:  # noqa: ASYNC110
        await asyncio.sleep(0)

    assert stored.status == "syncing"
    gate.set()
    await task


async def test_a_new_service_over_the_same_store_reports_the_last_state() -> None:
    first, states, events, secrets = make(FakeAdapter(script=[[make_event(id="a", start=NOW)]]))
    await first.sync("canvas")

    restarted, _, _, _ = make(FakeAdapter(), states=states, events=events, secrets=secrets)

    state = restarted.state("canvas")
    assert state is not None
    assert state.message == "Synced 1 items"


async def test_purge_deletes_the_stored_state_and_the_events() -> None:
    service, states, events, _ = make(FakeAdapter(script=[[make_event(id="a", start=NOW)]]))
    await service.sync("canvas")

    await service.purge("canvas")

    assert states.get("canvas") is None
    assert service.state("canvas") is None
    assert events.delete_source("canvas") == 0


async def test_a_sync_finishing_after_a_disconnect_leaves_no_state_in_the_store() -> None:
    gate = asyncio.Event()
    adapter = FakeAdapter(gate=gate, script=[[make_event(id="late", start=NOW)]])
    service, states, events, secrets = make(adapter)
    settings = SettingsService({"canvas": adapter}, secrets, service)

    running = asyncio.create_task(service.sync("canvas"))
    while adapter.in_flight == 0:  # noqa: ASYNC110
        await asyncio.sleep(0)
    await settings.disconnect("canvas")
    gate.set()
    await running

    assert states.get("canvas") is None
    assert events.delete_source("canvas") == 0


async def test_a_store_that_is_down_does_not_fail_the_sync(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, _, _, _ = make(
        FakeAdapter(script=[[make_event(id="a", start=NOW)]]), states=BrokenStateStore()
    )

    state = await service.sync("canvas")

    assert state.status == "ok"
    assert service.state("canvas") == state  # the memory copy still answers
    assert "fake-pw" not in caplog.text


async def test_without_a_store_nothing_changes() -> None:
    adapter = FakeAdapter(script=[[make_event(id="a", start=NOW)]])
    secrets = InMemorySecretStore()
    secrets.set("canvas", "token", TOKEN["token"])
    service = SyncService(
        {"canvas": adapter}, secrets, InMemoryEventStore(), FakeClock(NOW), sleep=RecordingSleep()
    )

    state = await service.sync("canvas")

    assert service.state("canvas") == state


async def test_a_stored_message_is_trimmed_to_200_characters() -> None:
    adapter = FakeAdapter(script=[TransientError("x" * 500)])
    service, states, _, _ = make(adapter)

    await service.sync("canvas")

    stored = states.get("canvas")
    assert stored is not None
    assert len(stored.message) <= 200
