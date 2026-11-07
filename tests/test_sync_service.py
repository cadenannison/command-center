"""SyncService: window, storage, retry policy, per-source state and error mapping."""

import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta

import pytest

from builders import NOW, make_event
from command_center.core.errors import AuthExpired, FatalError, TransientError
from command_center.core.windows import TimeWindow
from command_center.services.errors import UnknownSourceError
from command_center.services.sync import SyncService
from fake_adapter import (
    FakeAdapter,
    RecordingSleep,
    ThreadRecordingEventStore,
    ThreadRecordingSecretStore,
    UnavailableSecretStore,
)
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

CREDS = {"token": "fake-canvas-token-1234"}
EVERYTHING = TimeWindow(start=NOW - timedelta(days=400), end=NOW + timedelta(days=400))


def connected_secrets(*sources: str) -> InMemorySecretStore:
    secrets = InMemorySecretStore()
    for source in sources:
        for key, value in CREDS.items():
            secrets.set(source, key, value)
    return secrets


def make_service(
    adapters: list[FakeAdapter],
    *,
    secrets: InMemorySecretStore | None = None,
    events: InMemoryEventStore | None = None,
    sleep: RecordingSleep | None = None,
) -> SyncService:
    return SyncService(
        {adapter.name: adapter for adapter in adapters},
        secrets if secrets is not None else connected_secrets(*(a.name for a in adapters)),
        events if events is not None else InMemoryEventStore(),
        FakeClock(NOW),
        sleep=sleep or RecordingSleep(),
    )


async def test_sync_fetches_from_14_days_back_to_60_days_ahead_of_today() -> None:
    adapter = FakeAdapter()

    await make_service([adapter]).sync("canvas")

    (_, window) = adapter.fetches[0]
    assert window.start == datetime(2026, 10, 24, tzinfo=UTC)
    assert window.end == datetime(2027, 1, 6, tzinfo=UTC)


async def test_sync_passes_the_stored_credentials_to_the_adapter() -> None:
    adapter = FakeAdapter()

    await make_service([adapter]).sync("canvas")

    assert adapter.fetches[0][0] == CREDS


async def test_sync_stores_the_fetched_events() -> None:
    events = InMemoryEventStore()
    fetched = [make_event(id="a", start=NOW), make_event(id="b", start=NOW + timedelta(hours=1))]

    await make_service([FakeAdapter(script=[fetched])], events=events).sync("canvas")

    assert [e.id for e in events.query(EVERYTHING)] == ["a", "b"]


async def test_sync_reports_ok_with_the_time_of_the_sync() -> None:
    service = make_service([FakeAdapter(script=[[make_event(id="a", start=NOW)]])])

    state = await service.sync("canvas")

    assert (state.source, state.status, state.at) == ("canvas", "ok", NOW)
    assert state.message == "Synced 1 items"


async def test_state_returns_the_last_result_and_none_before_any_sync() -> None:
    service = make_service([FakeAdapter()])

    assert service.state("canvas") is None
    state = await service.sync("canvas")

    assert service.state("canvas") == state


async def test_sync_marks_the_source_syncing_from_the_start_until_it_finishes() -> None:
    gate = asyncio.Event()
    service = make_service([FakeAdapter(gate=gate)])

    running = asyncio.create_task(service.sync("canvas"))
    await asyncio.sleep(0)
    during = service.state("canvas")
    gate.set()
    final = await running

    assert during is not None
    assert (during.status, during.at) == ("syncing", NOW)
    assert (final.status, service.state("canvas")) == ("ok", final)


async def test_mark_syncing_records_the_state_without_fetching() -> None:
    adapter = FakeAdapter()
    service = make_service([adapter])

    state = service.mark_syncing("canvas")

    assert (state.source, state.status) == ("canvas", "syncing")
    assert service.state("canvas") == state
    assert adapter.fetches == []


async def test_marking_an_unknown_source_syncing_is_rejected() -> None:
    with pytest.raises(UnknownSourceError):
        make_service([FakeAdapter()]).mark_syncing("gmail")


async def test_an_unexpected_failure_never_leaves_the_source_syncing() -> None:
    service = make_service([FakeAdapter(script=[RuntimeError("bug")])])

    with pytest.raises(RuntimeError, match="bug"):
        await service.sync("canvas")

    state = service.state("canvas")
    assert state is not None
    assert (state.status, state.message) == ("error", "Sync failed unexpectedly")


async def test_forget_drops_the_remembered_state() -> None:
    service = make_service([FakeAdapter()])
    await service.sync("canvas")

    service.forget("canvas")

    assert service.state("canvas") is None


async def test_a_sync_that_finishes_after_forget_leaves_no_state_behind() -> None:
    gate = asyncio.Event()
    service = make_service([FakeAdapter(gate=gate)])

    running = asyncio.create_task(service.sync("canvas"))
    await asyncio.sleep(0)
    service.forget("canvas")
    gate.set()
    final = await running

    assert final.status == "ok"
    assert service.state("canvas") is None


async def test_a_failed_sync_after_forget_leaves_no_state_behind() -> None:
    gate = asyncio.Event()
    service = make_service([FakeAdapter(gate=gate, script=[RuntimeError("bug")])])

    running = asyncio.create_task(service.sync("canvas"))
    await asyncio.sleep(0)
    service.forget("canvas")
    gate.set()
    with pytest.raises(RuntimeError, match="bug"):
        await running

    assert service.state("canvas") is None


async def test_sync_of_a_source_without_credentials_asks_to_reconnect_without_fetching() -> None:
    adapter = FakeAdapter()

    state = await make_service([adapter], secrets=InMemorySecretStore()).sync("canvas")

    assert state.status == "reconnect"
    assert adapter.fetches == []


async def test_auth_expired_means_reconnect_and_is_not_retried() -> None:
    adapter = FakeAdapter(script=[AuthExpired("token rejected (401)")])
    sleep = RecordingSleep()

    state = await make_service([adapter], sleep=sleep).sync("canvas")

    assert state.status == "reconnect"
    assert len(adapter.fetches) == 1
    assert sleep.delays == []


async def test_transient_error_is_retried_with_doubling_backoff_until_it_succeeds() -> None:
    adapter = FakeAdapter(
        script=[TransientError("timeout"), TransientError("timeout"), [make_event(start=NOW)]]
    )
    sleep = RecordingSleep()

    state = await make_service([adapter], sleep=sleep).sync("canvas")

    assert state.status == "ok"
    assert len(adapter.fetches) == 3
    assert sleep.delays == [1.0, 2.0]


async def test_transient_error_gives_up_after_three_retries_and_reports_the_reason() -> None:
    adapter = FakeAdapter(script=[TransientError("rate limited (429)")])
    sleep = RecordingSleep()

    state = await make_service([adapter], sleep=sleep).sync("canvas")

    assert state.status == "error"
    assert "rate limited (429)" in state.message
    assert len(adapter.fetches) == 4
    assert sleep.delays == [1.0, 2.0, 4.0]


async def test_each_retry_is_logged_with_its_reason(caplog: pytest.LogCaptureFixture) -> None:
    adapter = FakeAdapter(script=[TransientError("timeout"), []])

    with caplog.at_level(logging.WARNING, logger="command_center.services.sync"):
        await make_service([adapter]).sync("canvas")

    (record,) = caplog.records
    assert record.getMessage() == "sync of canvas retry 1 in 1s: timeout"
    assert record.__dict__["source"] == "canvas"
    assert (record.__dict__["attempt"], record.__dict__["delay_seconds"]) == (1, 1.0)
    assert record.__dict__["reason"] == "timeout"


async def test_giving_up_logs_the_reason_in_the_message(caplog: pytest.LogCaptureFixture) -> None:
    adapter = FakeAdapter(script=[TransientError("rate limited (429)")])

    with caplog.at_level(logging.WARNING, logger="command_center.services.sync"):
        await make_service([adapter]).sync("canvas")

    assert "sync of canvas gave up: rate limited (429)" in caplog.messages


async def test_fatal_error_is_an_error_state_and_is_not_retried() -> None:
    adapter = FakeAdapter(script=[FatalError("malformed feed")])
    sleep = RecordingSleep()

    state = await make_service([adapter], sleep=sleep).sync("canvas")

    assert state.status == "error"
    assert "malformed feed" in state.message
    assert len(adapter.fetches) == 1
    assert sleep.delays == []


async def test_unavailable_secret_store_is_an_error_state_without_details() -> None:
    adapter = FakeAdapter()
    service = SyncService(
        {"canvas": adapter}, UnavailableSecretStore(), InMemoryEventStore(), FakeClock(NOW)
    )

    state = await service.sync("canvas")

    assert (state.status, state.message) == ("error", "secret store unavailable")
    assert adapter.fetches == []


async def test_syncing_an_unknown_source_is_rejected() -> None:
    with pytest.raises(UnknownSourceError):
        await make_service([FakeAdapter()]).sync("gmail")


async def test_sync_all_syncs_every_source_and_isolates_failures() -> None:
    good = FakeAdapter("canvas", script=[[make_event(id="a", start=NOW)]])
    bad = FakeAdapter("gmail", script=[FatalError("broken")])

    states = await make_service([good, bad]).sync_all()

    assert {s.source: s.status for s in states} == {"canvas": "ok", "gmail": "error"}


async def test_sync_all_with_no_sources_returns_nothing() -> None:
    assert await make_service([]).sync_all() == []


async def test_two_syncs_of_one_source_never_overlap() -> None:
    gate = asyncio.Event()
    adapter = FakeAdapter(gate=gate)
    service = make_service([adapter])

    first = asyncio.create_task(service.sync("canvas"))
    second = asyncio.create_task(service.sync("canvas"))
    await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(first, second)

    assert adapter.max_in_flight == 1
    assert len(adapter.fetches) == 2


async def test_store_calls_run_off_the_event_loop_thread() -> None:
    secrets = ThreadRecordingSecretStore()
    secrets.set("canvas", "token", "fake-canvas-token-1234")
    events = ThreadRecordingEventStore()
    service = SyncService({"canvas": FakeAdapter()}, secrets, events, FakeClock(NOW))

    await service.sync("canvas")

    loop_thread = threading.get_ident()
    assert secrets.threads
    assert events.threads
    assert loop_thread not in secrets.threads + events.threads
