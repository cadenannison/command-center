"""ReportSink on the SQL stores: generation check and writes together, stale rows cleaned (0075)."""

import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine

from builders import make_event
from command_center.core.schema import Event
from command_center.core.sync_state import SyncState
from queue_support import START, WINDOW
from sink_support import DATABASES, Stores, ok_state, open_engine, open_stores
from worker_support import events


@pytest.fixture(params=DATABASES)
def engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    yield from open_engine(request.param, tmp_path)


@pytest.fixture
def stores(engine: Engine) -> Stores:
    return open_stores(engine)


def ids(stores: Stores, source: str = "canvas") -> list[str]:
    return [e.id for e in stores.events.query(WINDOW) if e.source == source]


def late(minutes: int = 1) -> SyncState:
    return ok_state(at=START + timedelta(minutes=minutes))


def test_a_report_of_the_current_generation_is_applied(stores: Stores) -> None:
    stores.generations.bump("canvas")
    outcome = stores.sink.apply(1, WINDOW, events("a", "b"), ok_state(message="Synced 2 items"))
    assert outcome == "applied"
    assert ids(stores) == ["a", "b"]
    state = stores.states.get("canvas")
    assert state is not None
    assert state.message == "Synced 2 items"


def test_generation_zero_is_current_for_a_source_never_bumped(stores: Stores) -> None:
    assert stores.sink.apply(0, WINDOW, events("a"), ok_state()) == "applied"
    assert stores.generations.current("canvas") == 0  # the lock row does not change the number


@pytest.mark.parametrize("stale", [0, 2])
def test_a_report_of_another_generation_writes_nothing(stores: Stores, stale: int) -> None:
    stores.generations.bump("canvas")
    outcome = stores.sink.apply(stale, WINDOW, events("a"), ok_state())
    assert outcome == "not_current"
    assert ids(stores) == []
    assert stores.states.get("canvas") is None


def test_an_older_report_does_not_replace_a_newer_one(stores: Stores) -> None:
    stores.sink.apply(0, WINDOW, events("new"), late(5))
    outcome = stores.sink.apply(0, WINDOW, events("old"), ok_state())
    assert outcome == "older"
    assert ids(stores) == ["new"]
    state = stores.states.get("canvas")
    assert state is not None
    assert state.at == START + timedelta(minutes=5)


def test_a_state_only_report_keeps_the_events_and_replaces_the_state(stores: Stores) -> None:
    stores.sink.apply(0, WINDOW, events("a"), ok_state())
    problem = SyncState.model_validate(
        {
            "source": "canvas",
            "status": "reconnect",
            "message": "Credentials were rejected; reconnect",
            "at": START + timedelta(minutes=1),
        }
    )
    assert stores.sink.apply(0, WINDOW, None, problem) == "applied"
    assert ids(stores) == ["a"]
    state = stores.states.get("canvas")
    assert state is not None
    assert state.status == "reconnect"


def test_a_rejected_event_rolls_the_whole_report_back(stores: Stores) -> None:
    stores.sink.apply(0, WINDOW, events("a"), ok_state())
    foreign: list[Event] = [make_event(id="x", source="gmail", start=START)]
    with pytest.raises(ValueError, match="source"):
        stores.sink.apply(0, WINDOW, foreign, late())
    assert ids(stores) == ["a"]
    state = stores.states.get("canvas")
    assert state is not None
    assert state.at == START


def test_another_sources_rows_are_not_touched(stores: Stores) -> None:
    stores.sink.apply(0, WINDOW, events("g", source="gmail"), ok_state("gmail"))
    stores.generations.bump("canvas")
    stores.sink.apply(0, WINDOW, events("a"), ok_state())  # dropped
    stores.sink.purge_stale("canvas")
    assert ids(stores, "gmail") == ["g"]
    assert stores.states.get("gmail") is not None


class TestPurgeStale:
    def test_deletes_the_events_and_state_of_an_older_generation(self, stores: Stores) -> None:
        stores.sink.apply(0, WINDOW, events("a", "b"), ok_state())
        stores.generations.bump("canvas")

        assert stores.sink.purge_stale("canvas") is True

        assert ids(stores) == []
        assert stores.states.get("canvas") is None

    def test_deleting_twice_is_the_same_as_once(self, stores: Stores) -> None:
        stores.sink.apply(0, WINDOW, events("a"), ok_state())
        stores.generations.bump("canvas")
        stores.sink.purge_stale("canvas")
        assert stores.sink.purge_stale("canvas") is False
        assert ids(stores) == []

    def test_keeps_rows_written_under_the_current_generation(self, stores: Stores) -> None:
        stores.sink.apply(0, WINDOW, events("old"), ok_state())
        stores.generations.bump("canvas")
        stores.sink.apply(1, WINDOW, events("new"), late())

        assert stores.sink.purge_stale("canvas") is False  # a redelivered drop of the old report

        assert ids(stores) == ["new"]
        assert stores.states.get("canvas") is not None

    def test_a_source_with_nothing_stored_is_not_an_error(self, stores: Stores) -> None:
        assert stores.sink.purge_stale("canvas") is False


def test_applying_under_a_new_generation_clears_what_an_unfinished_purge_left(
    stores: Stores,
) -> None:
    # An event outside the new report's window, written under generation 0, never purged.
    outside = make_event(id="far", source="canvas", title="Far", start=START + timedelta(days=30))
    wide = WINDOW.model_copy(update={"end": START + timedelta(days=60)})
    stores.sink.apply(0, wide, [outside], ok_state())
    stores.generations.bump("canvas")

    stores.sink.apply(1, WINDOW, events("fresh"), late())

    assert [e.id for e in stores.events.query(wide)] == ["fresh"]


def test_leftovers_are_cleared_before_the_older_check_so_a_slow_clock_does_not_block_a_reconnect(
    stores: Stores,
) -> None:
    stores.sink.apply(0, WINDOW, events("leftover"), late(5))
    stores.generations.bump("canvas")

    # The new connection's worker clock is behind the leftover's `at`.
    outcome = stores.sink.apply(1, WINDOW, events("fresh"), ok_state())

    assert outcome == "applied"
    assert ids(stores) == ["fresh"]


def test_a_plain_state_put_keeps_the_generation_of_the_row(stores: Stores) -> None:
    stores.generations.bump("canvas")
    stores.sink.apply(1, WINDOW, events("a"), ok_state())
    stores.states.put(late(2))  # a writer that does not know about generations

    assert stores.sink.purge_stale("canvas") is False  # still generation 1, still current
    assert ids(stores) == ["a"]


def test_a_disconnect_racing_applies_in_other_threads_leaves_nothing(stores: Stores) -> None:
    """Applies of generation 0 race a disconnect (bump, then purge); none may survive it."""
    barrier = threading.Barrier(5)
    errors: list[BaseException] = []

    def apply(n: int) -> None:
        barrier.wait()
        try:
            for i in range(5):
                stores.sink.apply(
                    0,
                    WINDOW,
                    events(f"e{n}-{i}"),
                    ok_state(at=START + timedelta(seconds=n * 10 + i)),
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def disconnect() -> None:
        barrier.wait()
        try:
            stores.generations.bump("canvas")
            stores.events.delete_source("canvas")
            stores.states.delete("canvas")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=apply, args=(n,)) for n in range(4)]
    threads.append(threading.Thread(target=disconnect))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []

    # No backstop here: the generation check inside the transaction is what keeps this empty.
    assert stores.generations.current("canvas") == 1
    assert ids(stores) == []
    assert stores.states.get("canvas") is None
