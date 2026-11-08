"""Normalizer: replace the events, record the state, and be safe to run twice."""

from datetime import timedelta

import pytest

from command_center.adapters.inprocess_reports import InProcessReportStream
from fakes import FakeClock, InMemoryEventStore
from queue_support import START
from worker_support import (
    VISIBILITY,
    InMemorySyncStateStore,
    events,
    make_normalizer,
    make_report,
)


class Rig:
    def __init__(self) -> None:
        self.clock = FakeClock(START)
        self.reports = InProcessReportStream(self.clock, visibility_timeout=VISIBILITY)
        self.store = InMemoryEventStore()
        self.states = InMemorySyncStateStore()
        self.normalizer = make_normalizer(self.reports, self.store, self.states)


@pytest.fixture
def rig() -> Rig:
    return Rig()


def stored_ids(rig: Rig) -> list[str]:
    from queue_support import WINDOW  # noqa: PLC0415

    return [e.id for e in rig.store.query(WINDOW)]


async def test_an_ok_report_replaces_the_events_and_records_the_state(rig: Rig) -> None:
    await rig.reports.publish(make_report(items=events("a", "b")))
    assert await rig.normalizer.run_once() is True

    assert stored_ids(rig) == ["a", "b"]
    state = rig.states.get("canvas")
    assert state is not None
    assert (state.status, state.message, state.at) == ("ok", "Synced 2 items", START)


async def test_nothing_waiting_is_a_quiet_no(rig: Rig) -> None:
    assert await rig.normalizer.run_once() is False


async def test_a_later_report_deletes_what_the_source_no_longer_returns(rig: Rig) -> None:
    await rig.reports.publish(make_report("r1", items=events("a", "b")))
    await rig.reports.publish(make_report("r2", items=events("b"), at_offset=timedelta(minutes=1)))
    await rig.normalizer.run_once()
    await rig.normalizer.run_once()
    assert stored_ids(rig) == ["b"]


@pytest.mark.parametrize("status", ["reconnect", "error"])
async def test_a_failure_report_records_the_state_and_keeps_the_stored_events(
    rig: Rig, status: str
) -> None:
    await rig.reports.publish(make_report("r1", items=events("a")))
    await rig.reports.publish(
        make_report(
            "r2",
            status=status,
            message="Credentials were rejected; reconnect",
            at_offset=timedelta(minutes=1),
        )
    )
    await rig.normalizer.run_once()
    await rig.normalizer.run_once()

    assert stored_ids(rig) == ["a"]
    state = rig.states.get("canvas")
    assert state is not None
    assert (state.status, state.message) == (status, "Credentials were rejected; reconnect")


async def test_a_redelivered_report_leaves_identical_state(rig: Rig) -> None:
    report = make_report(items=events("a", "b"))
    await rig.reports.publish(report)
    await rig.reports.publish(report.model_copy(update={"id": "r1-again"}))
    await rig.normalizer.run_once()
    first = (stored_ids(rig), rig.states.get("canvas"))
    await rig.normalizer.run_once()
    assert (stored_ids(rig), rig.states.get("canvas")) == first


async def test_an_older_report_arriving_late_does_not_overwrite_a_newer_one(rig: Rig) -> None:
    await rig.reports.publish(make_report("new", items=events("b"), at_offset=timedelta(hours=1)))
    await rig.reports.publish(make_report("old", items=events("a")))
    await rig.normalizer.run_once()
    await rig.normalizer.run_once()
    assert stored_ids(rig) == ["b"]
    state = rig.states.get("canvas")
    assert state is not None
    assert state.at == START + timedelta(hours=1)


async def test_a_report_with_an_event_of_another_source_is_dead_lettered(rig: Rig) -> None:
    await rig.reports.publish(make_report(items=events("a", source="gmail")))
    await rig.normalizer.run_once()

    assert stored_ids(rig) == []
    assert rig.states.get("canvas") is None
    [dead] = await rig.reports.list_dead_reports()
    assert (dead.source, dead.reason) == ("canvas", "ValueError")
    rig.clock.advance(VISIBILITY * 2)
    assert await rig.normalizer.run_once() is False


async def test_a_message_that_could_hold_an_address_is_redacted_in_the_state(rig: Rig) -> None:
    await rig.reports.publish(
        make_report(status="error", message="Sync failed: ann@example.com 5551234567")
    )
    await rig.normalizer.run_once()
    state = rig.states.get("canvas")
    assert state is not None
    assert "ann@example.com" not in state.message
    assert "5551234567" not in state.message
