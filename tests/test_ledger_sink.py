"""The item ledger through the report sink and the normalizer (distributed mode, decision 0121).

The ledger rows are written in the sink's transaction, behind the generation lock, so a stale
report writes nothing and a purge of an old generation takes the ledger rows with it. The sink
cases run on SQLite and, with CC_TEST_POSTGRES_URL, on Postgres; the normalizer cases run on the
in-process stream and, with CC_TEST_REDIS_URL, on Redis.
"""

import os
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from builders import NOW, make_event
from command_center.core.ledger import LedgerEntry
from command_center.core.ports import ApplyOutcome, ReportSink
from command_center.core.schema import Event
from command_center.core.sync_state import SyncState
from command_center.core.windows import TimeWindow
from command_center.workers.normalizer import Normalizer
from ledger_support import LedgerRig, open_ledger_rig
from queue_support import REDIS_URL_ENV, START, WINDOW
from sink_support import DATABASES, ok_state, open_engine
from worker_support import (
    Backend,
    events,
    inprocess_backend,
    make_report,
    redis_backend,
)

EVERYTHING = TimeWindow(start=NOW - timedelta(days=400), end=NOW + timedelta(days=400))
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


@pytest.fixture(params=DATABASES)
def rig(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine(request.param, tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def sqlite_rig(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest_asyncio.fixture(params=BACKENDS)
async def backend(request: pytest.FixtureRequest) -> AsyncIterator[Backend]:
    factory = inprocess_backend if request.param == "inprocess" else redis_backend
    async for item in factory():
        yield item


def later(minutes: int) -> SyncState:
    return ok_state(at=START + timedelta(minutes=minutes))


def done(item_id: str) -> Event:
    return make_event(
        id=item_id, source="canvas", title=f"Item {item_id}", start=START, status="done"
    )


def history(rig: LedgerRig) -> list[LedgerEntry]:
    return rig.ledger.history(EVERYTHING)


def test_an_applied_report_notes_what_left_the_source_at_the_reports_own_time(
    rig: LedgerRig,
) -> None:
    rig.sink.apply(0, WINDOW, events("a", "b"), later(0))
    assert rig.sink.apply(0, WINDOW, events("a"), later(5)) == "applied"

    (entry,) = history(rig)
    assert (entry.item_id, entry.group) == ("b", "gone")
    assert entry.at == START + timedelta(minutes=5)  # the report's time, not this process's clock


def test_an_applied_report_notes_a_completion_at_the_reports_own_time(rig: LedgerRig) -> None:
    rig.sink.apply(0, WINDOW, events("a"), later(0))
    rig.sink.apply(0, WINDOW, [done("a")], later(7))

    (entry,) = history(rig)
    assert (entry.item_id, entry.group, entry.at) == (
        "a",
        "done_by_source",
        START + timedelta(minutes=7),
    )


def test_a_report_of_a_stale_generation_writes_no_ledger_rows(rig: LedgerRig) -> None:
    rig.generations.bump("canvas")
    assert rig.sink.apply(1, WINDOW, events("a", "b"), later(0)) == "applied"
    rig.generations.bump("canvas")  # a disconnect and reconnect: generation 1 is stale now
    rig.sink.purge_stale("canvas")

    outcome = rig.sink.apply(1, WINDOW, [done("a")], later(1))

    assert outcome == "not_current"
    assert history(rig) == []
    assert rig.ledger.marks(["a", "b"]) == {}


def test_a_report_older_than_the_stored_state_writes_no_ledger_rows(rig: LedgerRig) -> None:
    rig.sink.apply(0, WINDOW, events("a", "b"), later(10))

    outcome = rig.sink.apply(0, WINDOW, events("a"), later(1))

    assert outcome == "older"
    assert history(rig) == []


def test_a_rejected_report_changes_neither_events_nor_ledger(rig: LedgerRig) -> None:
    rig.sink.apply(0, WINDOW, events("a", "b"), later(0))
    foreign = events("z", source="gmail")

    with pytest.raises(ValueError, match="source"):
        rig.sink.apply(0, WINDOW, [*events("a"), *foreign], later(1))

    assert history(rig) == []
    assert {e.id for e in rig.events.query(WINDOW)} == {"a", "b"}


def test_purging_a_stale_generation_deletes_its_ledger_rows_and_notes(rig: LedgerRig) -> None:
    rig.sink.apply(0, WINDOW, events("a", "b"), later(0))
    rig.sink.apply(0, WINDOW, events("a"), later(1))  # b is removed: a ledger row
    rig.ledger.set_note("a", "keep this", NOW)
    rig.generations.bump("canvas")  # a disconnect

    assert rig.sink.purge_stale("canvas") is True

    assert history(rig) == []
    assert rig.ledger.marks(["a", "b"]) == {}


def test_purging_a_current_generation_keeps_the_ledger(rig: LedgerRig) -> None:
    rig.sink.apply(0, WINDOW, events("a", "b"), later(0))
    rig.sink.apply(0, WINDOW, events("a"), later(1))

    assert rig.sink.purge_stale("canvas") is False

    assert [e.item_id for e in history(rig)] == ["b"]


def test_an_apply_clears_ledger_rows_left_by_an_unfinished_purge(rig: LedgerRig) -> None:
    rig.sink.apply(0, WINDOW, events("a", "b"), later(0))
    rig.sink.apply(0, WINDOW, events("a"), later(1))
    rig.ledger.set_note("a", "old connection", NOW)
    rig.generations.bump("canvas")  # the disconnect's purge never ran

    assert rig.sink.apply(1, WINDOW, events("c"), later(2)) == "applied"

    assert history(rig) == []
    assert rig.ledger.marks(["a", "b", "c"]) == {}


def test_other_sources_ledger_rows_are_not_touched_by_a_purge(rig: LedgerRig) -> None:
    rig.sink.apply(0, WINDOW, events("g1", "g2", source="gmail"), ok_state("gmail", at=START))
    rig.sink.apply(0, WINDOW, events("g1", source="gmail"), ok_state("gmail", at=START))
    rig.generations.bump("canvas")

    rig.sink.purge_stale("canvas")

    assert [e.item_id for e in history(rig)] == ["g2"]


class Killed(BaseException):  # like a SIGKILL: no `except Exception` sees it
    """Raised where a process would have died."""


class DiesAfterTheWrite:
    """The sink writes, a disconnect's bump lands, and the process dies before its second check."""

    def __init__(self, inner: ReportSink, rig: LedgerRig) -> None:
        self._inner = inner
        self._rig = rig

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
        self._rig.generations.bump(state.source)
        raise Killed

    def purge_stale(self, source: str, *, user_id: str = "local") -> bool:
        return self._inner.purge_stale(source, user_id=user_id)


def normalizer(
    backend: Backend, rig: LedgerRig, sink: ReportSink | None = None, consumer: str = "norm-1"
) -> Normalizer:
    return Normalizer(
        backend.reports(),
        rig.events,
        rig.states,
        generations=rig.generations,
        sink=sink or rig.sink,
        consumer=consumer,
        block_ms=0,
    )


async def drain(worker: Normalizer) -> None:
    while await worker.run_once():
        pass


async def test_the_normalizer_notes_what_a_report_removed(
    backend: Backend, sqlite_rig: LedgerRig
) -> None:
    await backend.reports().publish(make_report("r1", items=events("a", "b")))
    await backend.reports().publish(
        make_report("r2", items=events("a"), at_offset=timedelta(minutes=3))
    )

    await drain(normalizer(backend, sqlite_rig))

    (entry,) = history(sqlite_rig)
    assert (entry.item_id, entry.group, entry.at) == ("b", "gone", START + timedelta(minutes=3))


async def test_a_dropped_stale_report_writes_no_ledger_rows(
    backend: Backend, sqlite_rig: LedgerRig
) -> None:
    sqlite_rig.generations.bump("canvas")
    sqlite_rig.sink.apply(1, WINDOW, events("fresh"), later(0))
    await backend.reports().publish(make_report("old", items=[done("fresh")]))  # generation 0

    await drain(normalizer(backend, sqlite_rig))

    assert history(sqlite_rig) == []
    assert await backend.reports().list_dead_reports() == []


async def test_a_crash_after_the_write_leaves_no_ledger_rows_after_redelivery(
    backend: Backend, sqlite_rig: LedgerRig
) -> None:
    sqlite_rig.sink.apply(0, WINDOW, events("a", "b"), later(0))
    await backend.reports().publish(
        make_report("r2", items=events("a"), at_offset=timedelta(minutes=2))
    )
    with pytest.raises(Killed):
        await normalizer(
            backend, sqlite_rig, sink=DiesAfterTheWrite(sqlite_rig.sink, sqlite_rig)
        ).run_once()
    assert [e.item_id for e in history(sqlite_rig)] == ["b"]  # the write survived the crash

    await backend.expire()
    await drain(normalizer(backend, sqlite_rig, consumer="norm-2"))

    assert history(sqlite_rig) == []
    assert sqlite_rig.states.get("canvas") is None
