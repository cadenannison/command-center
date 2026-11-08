"""The sync loop: one round at startup, one per interval, and no failure ends it."""

import asyncio
import logging
from collections.abc import Sequence

import pytest

from builders import NOW
from command_center.services.models import SyncState
from command_center.services.scheduler import SyncScheduler
from command_center.services.sync import SyncService
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore


class ScriptedSync(SyncService):
    """A SyncService whose sync_all counts calls and raises what the script says."""

    def __init__(self, outcomes: Sequence[Exception | None] = ()) -> None:
        super().__init__({}, InMemorySecretStore(), InMemoryEventStore(), FakeClock(NOW))
        self._outcomes = list(outcomes)
        self.calls = 0

    async def sync_all(self) -> list[SyncState]:
        self.calls += 1
        if self._outcomes:
            outcome = self._outcomes.pop(0)
            if outcome is not None:
                raise outcome
        return []


class ParkingSleep:
    """Records each requested delay; after `rounds` sleeps it signals and parks the loop."""

    def __init__(self, rounds: int) -> None:
        self.delays: list[float] = []
        self.reached = asyncio.Event()
        self._rounds = rounds

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        if len(self.delays) >= self._rounds:
            self.reached.set()
            await asyncio.Event().wait()


async def run_rounds(sync: ScriptedSync, sleep: ParkingSleep, interval_minutes: int = 30) -> None:
    scheduler = SyncScheduler(sync, interval_minutes, sleep=sleep)
    scheduler.start()
    await asyncio.wait_for(sleep.reached.wait(), timeout=5)
    await scheduler.stop()


async def test_the_first_sync_runs_before_the_first_wait() -> None:
    sync = ScriptedSync()
    sleep = ParkingSleep(rounds=1)

    await run_rounds(sync, sleep)

    assert sync.calls == 1


async def test_each_round_waits_the_configured_interval_in_seconds() -> None:
    sync = ScriptedSync()
    sleep = ParkingSleep(rounds=3)

    await run_rounds(sync, sleep, interval_minutes=15)

    assert sleep.delays == [900, 900, 900]
    assert sync.calls == 3


async def test_a_failing_round_is_logged_by_class_and_the_loop_carries_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sync = ScriptedSync([RuntimeError("boom fake-secret-token"), None])
    sleep = ParkingSleep(rounds=2)

    with caplog.at_level(logging.WARNING):
        await run_rounds(sync, sleep)

    assert sync.calls == 2
    assert "RuntimeError" in caplog.text
    assert "fake-secret-token" not in caplog.text


async def test_stop_ends_the_loop_and_a_second_stop_is_harmless() -> None:
    sync = ScriptedSync()
    sleep = ParkingSleep(rounds=1)
    scheduler = SyncScheduler(sync, 30, sleep=sleep)
    scheduler.start()
    await asyncio.wait_for(sleep.reached.wait(), timeout=5)

    await scheduler.stop()
    await scheduler.stop()

    assert sync.calls == 1


async def test_starting_twice_runs_one_loop() -> None:
    sync = ScriptedSync()
    sleep = ParkingSleep(rounds=1)
    scheduler = SyncScheduler(sync, 30, sleep=sleep)

    scheduler.start()
    scheduler.start()
    await asyncio.wait_for(sleep.reached.wait(), timeout=5)
    await scheduler.stop()

    assert sync.calls == 1


class BlockedSync(ScriptedSync):
    """A sync_all that starts and then waits forever, like a slow source."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def sync_all(self) -> list[SyncState]:
        self.started.set()
        await asyncio.Event().wait()
        return []


async def test_stop_during_a_running_sync_cancels_it_and_returns() -> None:
    sync = BlockedSync()
    scheduler = SyncScheduler(sync, 30, sleep=ParkingSleep(rounds=1))
    scheduler.start()
    await asyncio.wait_for(sync.started.wait(), timeout=5)

    await asyncio.wait_for(scheduler.stop(), timeout=5)

    assert sync.started.is_set()
