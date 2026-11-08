"""The normalizer drops reports from before a disconnect and leaves nothing behind (0074)."""

from collections.abc import Sequence
from datetime import timedelta

import pytest

from command_center.adapters.inprocess_reports import InProcessReportStream
from command_center.core.jobs import SyncReport
from command_center.core.schema import Event
from command_center.core.windows import TimeWindow
from command_center.workers.normalizer import Normalizer
from fakes import FakeClock, InMemoryEventStore
from generation_support import InMemoryGenerationStore
from queue_support import START, WINDOW
from worker_support import (
    VISIBILITY,
    ClockSleep,
    InMemorySyncStateStore,
    events,
    make_report,
)


def report(generation: int, report_id: str = "r1", **kwargs: object) -> SyncReport:
    return make_report(report_id, **kwargs).model_copy(update={"generation": generation})  # type: ignore[arg-type]


class Rig:
    def __init__(self, store: InMemoryEventStore | None = None) -> None:
        self.clock = FakeClock(START)
        self.reports = InProcessReportStream(self.clock, visibility_timeout=VISIBILITY)
        self.store = store or InMemoryEventStore()
        self.states = InMemorySyncStateStore()
        self.generations = InMemoryGenerationStore()
        self.normalizer = Normalizer(
            self.reports,
            self.store,
            self.states,
            generations=self.generations,
            consumer="norm-1",
            block_ms=0,
            sleep=ClockSleep(self.clock),
        )

    def disconnect(self, source: str = "canvas") -> None:
        """What SettingsService.disconnect does to the shared stores."""
        self.generations.bump(source)
        self.store.delete_source(source)
        self.states.delete(source)

    def stored(self) -> list[str]:
        return [e.id for e in self.store.query(WINDOW)]

    async def drain(self) -> None:
        while await self.normalizer.run_once():
            pass


@pytest.fixture
def rig() -> Rig:
    return Rig()


async def test_a_report_with_the_current_generation_is_applied(rig: Rig) -> None:
    rig.generations.bump("canvas")
    await rig.reports.publish(report(1, items=events("a")))
    await rig.drain()
    assert rig.stored() == ["a"]
    assert rig.states.get("canvas") is not None


async def test_a_report_that_arrives_after_a_disconnect_leaves_no_events_or_state(rig: Rig) -> None:
    await rig.reports.publish(report(0, items=events("a", "b")))  # fetched before the disconnect
    rig.disconnect()

    await rig.drain()

    assert rig.stored() == []
    assert rig.states.get("canvas") is None


async def test_a_redelivered_report_after_a_disconnect_leaves_nothing_either(rig: Rig) -> None:
    await rig.reports.publish(report(0, items=events("a")))
    await rig.drain()
    assert rig.stored() == ["a"]
    rig.disconnect()

    await rig.reports.publish(report(0, items=events("a")))  # the same report, delivered again
    await rig.drain()

    assert rig.stored() == []
    assert rig.states.get("canvas") is None


async def test_a_dropped_report_is_acked_so_it_is_not_delivered_again(rig: Rig) -> None:
    await rig.reports.publish(report(0, items=events("a")))
    rig.disconnect()
    await rig.normalizer.run_once()

    rig.clock.advance(VISIBILITY * 2)

    assert await rig.normalizer.run_once() is False
    assert await rig.reports.list_dead_reports() == []


@pytest.mark.parametrize("status", ["reconnect", "error"])
async def test_a_state_only_report_from_before_a_disconnect_records_nothing(
    rig: Rig, status: str
) -> None:
    await rig.reports.publish(report(0, status=status, message="Credentials were rejected"))
    rig.disconnect()

    await rig.drain()

    assert rig.states.get("canvas") is None


async def test_a_reconnect_after_a_disconnect_syncs_normally(rig: Rig) -> None:
    await rig.reports.publish(report(0, "old", items=events("stale")))
    rig.disconnect()
    await rig.reports.publish(
        report(1, "new", items=events("fresh"), at_offset=timedelta(minutes=1))
    )

    await rig.drain()

    assert rig.stored() == ["fresh"]
    state = rig.states.get("canvas")
    assert state is not None
    assert state.message == "Synced 1 items"


async def test_a_disconnect_of_one_source_does_not_drop_another_sources_report(rig: Rig) -> None:
    rig.disconnect("gmail")
    await rig.reports.publish(report(0, items=events("a")))
    await rig.drain()
    assert rig.stored() == ["a"]


class DisconnectsWhileReplacing(InMemoryEventStore):
    """The disconnect lands between the normalizer's generation check and its write finishing."""

    def __init__(self) -> None:
        super().__init__()
        self.rig: Rig | None = None
        self.fired = False

    def replace(  # type: ignore[override]
        self,
        source: str,
        window: TimeWindow,
        events: Sequence[Event],
        *,
        user_id: str = "local",
    ) -> int:
        written = super().replace(source, window, events, user_id=user_id)
        if not self.fired and self.rig is not None:
            self.fired = True
            # The disconnect's own purge ran before the write above landed in a real store, so
            # only the bump is left for the normalizer to notice.
            self.rig.generations.bump(source)
        return written


async def test_a_disconnect_that_lands_while_the_report_is_being_applied_is_cleaned_up() -> None:
    store = DisconnectsWhileReplacing()
    rig = Rig(store)
    store.rig = rig
    await rig.reports.publish(report(0, items=events("a", "b")))

    await rig.drain()

    assert rig.stored() == []
    assert rig.states.get("canvas") is None


class DisconnectsWhileRecordingState(InMemorySyncStateStore):
    def __init__(self, rig_ref: list[Rig]) -> None:
        super().__init__()
        self._rig_ref = rig_ref
        self.fired = False

    def put(self, state, *, user_id: str = "local") -> None:  # type: ignore[no-untyped-def]  # noqa: ANN001
        super().put(state, user_id=user_id)
        if not self.fired:
            self.fired = True
            self._rig_ref[0].generations.bump(state.source)


async def test_a_disconnect_between_the_events_and_the_state_write_is_cleaned_up() -> None:
    rig_ref: list[Rig] = []
    rig = Rig()
    states = DisconnectsWhileRecordingState(rig_ref)
    rig.states = states
    rig.normalizer = Normalizer(
        rig.reports,
        rig.store,
        states,
        generations=rig.generations,
        consumer="norm-1",
        block_ms=0,
        sleep=ClockSleep(rig.clock),
    )
    rig_ref.append(rig)
    await rig.reports.publish(report(0, items=events("a")))

    await rig.drain()

    assert rig.stored() == []
    assert rig.states.get("canvas") is None


async def test_without_a_generation_store_every_report_is_applied(rig: Rig) -> None:
    # The pre-0074 wiring (tests and tools that build a Normalizer by hand) is unchanged.
    plain = Normalizer(
        rig.reports,
        rig.store,
        rig.states,
        consumer="norm-2",
        block_ms=0,
        sleep=ClockSleep(rig.clock),
    )
    await rig.reports.publish(report(0, items=events("a")))
    await plain.run_once()
    assert rig.stored() == ["a"]
