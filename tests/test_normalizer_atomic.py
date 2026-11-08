"""The normalizer over a ReportSink: crash recovery and racing normalizers (decision 0075).

Each case runs on the in-process report stream always, and on Redis when CC_TEST_REDIS_URL is set.
The stores are the real SQL ones in a temp SQLite file, because the point is what a database
transaction does and does not guarantee.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio

import worker_support
from command_center.core.jobs import DeadReport, SyncReport
from command_center.core.ports import ApplyOutcome, ReportSink, ReportStream
from command_center.core.schema import Event
from command_center.core.sync_state import SyncState
from command_center.core.windows import TimeWindow
from command_center.workers.normalizer import Normalizer
from queue_support import REDIS_URL_ENV, WINDOW
from sink_support import Stores, open_engine, open_stores
from worker_support import (
    Backend,
    ClockSleep,
    events,
    inprocess_backend,
    make_report,
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


class NormalizerKilled(BaseException):  # like a SIGKILL: no `except Exception` sees it
    """Raised where a process would have died."""


def report(generation: int, report_id: str = "r1", **kwargs: object) -> SyncReport:
    return make_report(report_id, **kwargs).model_copy(update={"generation": generation})  # type: ignore[arg-type]


def normalizer(
    backend: Backend,
    stores: Stores,
    sink: ReportSink | None = None,
    reports: ReportStream | None = None,
    consumer: str = "norm-1",
) -> Normalizer:
    return Normalizer(
        reports or backend.reports(),
        stores.events,
        stores.states,
        generations=stores.generations,
        sink=sink or stores.sink,
        consumer=consumer,
        block_ms=0,
        sleep=ClockSleep(backend.clock),
    )


def stored(stores: Stores) -> list[str]:
    return [e.id for e in stores.events.query(WINDOW)]


async def drain(n: Normalizer) -> None:
    while await n.run_once():
        pass


def disconnect(stores: Stores, source: str = "canvas") -> None:
    """What SettingsService.disconnect does to the shared stores."""
    stores.generations.bump(source)
    stores.events.delete_source(source)
    stores.states.delete(source)


class DiesAfterTheWrite:
    """The sink writes, then a disconnect's bump lands and the process dies before its check.

    The disconnect's purge ran before the write, so only the bump is left for anyone to see.
    """

    def __init__(self, inner: ReportSink, stores: Stores) -> None:
        self._inner = inner
        self._stores = stores

    def apply(
        self,
        generation: int,
        window: TimeWindow,
        events: Sequence[Event] | None,
        state: SyncState,
        *,
        user_id: str = "local",
    ) -> ApplyOutcome:
        self._inner.apply(generation, window, events, state, user_id=user_id)
        self._stores.generations.bump(state.source)
        raise NormalizerKilled

    def purge_stale(self, source: str, *, user_id: str = "local") -> bool:
        return self._inner.purge_stale(source, user_id=user_id)


async def test_a_crash_between_the_write_and_the_check_leaves_the_source_empty_after_redelivery(
    backend: Backend, stores: Stores
) -> None:
    await backend.reports().publish(report(0, items=events("a", "b")))

    dying = normalizer(backend, stores, sink=DiesAfterTheWrite(stores.sink, stores))
    with pytest.raises(NormalizerKilled):
        await dying.run_once()
    assert stored(stores) == ["a", "b"]  # the write survived the crash: the gap of 0074

    await backend.expire()  # the visibility timeout passes; the report is delivered again
    survivor = normalizer(backend, stores, consumer="norm-2")
    assert await survivor.run_once() is True

    assert stored(stores) == []
    assert stores.states.get("canvas") is None
    assert await survivor.run_once() is False  # and it was acked


async def test_the_redelivered_drop_does_not_touch_data_of_the_new_connection(
    backend: Backend, stores: Stores
) -> None:
    await backend.reports().publish(report(0, "old", items=events("stale")))
    with pytest.raises(NormalizerKilled):
        await normalizer(backend, stores, sink=DiesAfterTheWrite(stores.sink, stores)).run_once()

    # The user reconnects before the old report comes back; the new fetch is applied first.
    await backend.reports().publish(
        report(1, "new", items=events("fresh"), at_offset=timedelta(minutes=1))
    )
    await backend.expire()
    await drain(normalizer(backend, stores, consumer="norm-2"))

    assert stored(stores) == ["fresh"]
    state = stores.states.get("canvas")
    assert state is not None
    assert state.message == "Synced 1 items"


async def test_dropping_the_same_stale_report_again_is_a_no_op(
    backend: Backend, stores: Stores
) -> None:
    disconnect(stores)
    stores.sink.apply(1, WINDOW, events("fresh"), make_state())
    for round_ in ("first", "again"):
        await backend.reports().publish(report(0, f"old-{round_}", items=events("stale")))
        await drain(normalizer(backend, stores))
        assert stored(stores) == ["fresh"]
    assert await backend.reports().list_dead_reports() == []


def make_state() -> SyncState:
    return SyncState.model_validate(
        {"source": "canvas", "status": "ok", "message": "Synced 1 items", "at": make_report().at}
    )


class HoldsAfterConsuming:
    """A ReportStream whose consume parks once it has a report: a slow normalizer."""

    def __init__(self, inner: ReportStream) -> None:
        self._inner = inner
        self.holding = asyncio.Event()
        self.release = asyncio.Event()

    async def publish(self, report: SyncReport) -> None:
        await self._inner.publish(report)

    async def consume(self, group: str, consumer: str, block_ms: int) -> SyncReport | None:
        taken = await self._inner.consume(group, consumer, block_ms)
        if taken is not None:
            self.holding.set()
            await self.release.wait()
        return taken

    async def ack(self, report: SyncReport) -> None:
        await self._inner.ack(report)

    async def dead_letter(self, report: SyncReport, reason: str) -> None:
        await self._inner.dead_letter(report, reason)

    async def list_dead_reports(self) -> list[DeadReport]:
        return await self._inner.list_dead_reports()


async def test_a_slow_normalizer_cannot_undo_what_a_fast_one_applied_after_a_reconnect(
    backend: Backend, stores: Stores
) -> None:
    await backend.reports().publish(report(0, "old", items=events("stale")))
    slow_reports = HoldsAfterConsuming(backend.reports())
    slow = asyncio.create_task(
        normalizer(backend, stores, reports=slow_reports, consumer="slow").run_once()
    )
    await slow_reports.holding.wait()  # the slow normalizer holds the generation-0 report

    disconnect(stores)  # the user disconnects and connects again: jobs now carry generation 1
    await backend.reports().publish(
        report(1, "new", items=events("fresh"), at_offset=timedelta(minutes=1))
    )
    await drain(normalizer(backend, stores, consumer="fast"))
    assert stored(stores) == ["fresh"]

    slow_reports.release.set()
    assert await slow is True

    assert stored(stores) == ["fresh"]
    state = stores.states.get("canvas")
    assert state is not None
    assert state.at == make_report("new", at_offset=timedelta(minutes=1)).at


class ReconnectsMidApply:
    """While a slow normalizer is applying, the user disconnects, reconnects and a fast one applies.

    All of it happens after the slow normalizer's transaction and before its check afterwards.
    """

    def __init__(self, inner: ReportSink, stores: Stores) -> None:
        self._inner = inner
        self._stores = stores
        self.fired = False

    def apply(
        self,
        generation: int,
        window: TimeWindow,
        events: Sequence[Event] | None,
        state: SyncState,
        *,
        user_id: str = "local",
    ) -> ApplyOutcome:
        outcome = self._inner.apply(generation, window, events, state, user_id=user_id)
        if not self.fired:
            self.fired = True
            disconnect(self._stores)
            fresh = state.model_copy(update={"at": state.at + timedelta(minutes=1)})
            self._inner.apply(1, window, worker_support.events("fresh"), fresh, user_id=user_id)
        return outcome

    def purge_stale(self, source: str, *, user_id: str = "local") -> bool:
        return self._inner.purge_stale(source, user_id=user_id)


async def test_a_normalizer_that_finds_a_disconnect_after_its_write_deletes_only_its_own_rows(
    backend: Backend, stores: Stores
) -> None:
    await backend.reports().publish(report(0, items=events("stale")))
    slow = normalizer(backend, stores, sink=ReconnectsMidApply(stores.sink, stores))

    await drain(slow)

    assert stored(stores) == ["fresh"]
    assert stores.states.get("canvas") is not None


async def test_a_disconnect_after_the_write_but_before_the_check_leaves_the_source_empty(
    backend: Backend, stores: Stores
) -> None:
    class DisconnectsAfterApply(ReconnectsMidApply):
        def apply(  # type: ignore[override]
            self,
            generation: int,
            window: TimeWindow,
            events: Sequence[Event] | None,
            state: SyncState,
            *,
            user_id: str = "local",
        ) -> ApplyOutcome:
            outcome = self._inner.apply(generation, window, events, state, user_id=user_id)
            self._stores.generations.bump(state.source)  # the purge ran before our write
            return outcome

    await backend.reports().publish(report(0, items=events("a")))
    await drain(normalizer(backend, stores, sink=DisconnectsAfterApply(stores.sink, stores)))

    assert stored(stores) == []
    assert stores.states.get("canvas") is None


async def test_a_report_for_a_source_with_nothing_connected_anymore_is_acked_and_dropped(
    backend: Backend, stores: Stores
) -> None:
    disconnect(stores)
    await backend.reports().publish(report(0, items=events("a")))
    n = normalizer(backend, stores)
    assert await n.run_once() is True
    await backend.expire()
    assert await n.run_once() is False
    assert stored(stores) == []


async def test_a_normalizer_without_a_sink_still_applies_reports_the_old_way(
    backend: Backend, stores: Stores
) -> None:
    plain = Normalizer(
        backend.reports(),
        stores.events,
        stores.states,
        generations=stores.generations,
        consumer="plain",
        block_ms=0,
        sleep=ClockSleep(backend.clock),
    )
    await backend.reports().publish(report(0, items=events("a")))
    await drain(plain)
    assert stored(stores) == ["a"]
