"""replace and delete_source for every EventStore: the in-memory fake and SQLite must agree."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from builders import make_event
from command_center.core.ports import EventStore
from command_center.core.schema import Event
from command_center.core.windows import TimeWindow
from command_center.storage.sqlite import SqliteEventStore, create_event_store
from fakes import InMemoryEventStore

DAY = TimeWindow(
    start=datetime(2026, 11, 7, tzinfo=UTC),
    end=datetime(2026, 11, 8, tzinfo=UTC),
)
EVERYTHING = TimeWindow(start=DAY.start - timedelta(days=365), end=DAY.end + timedelta(days=365))
NOON = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
NEXT_WEEK = NOON + timedelta(days=7)


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[EventStore]:
    if request.param == "memory":
        yield InMemoryEventStore()
        return
    sqlite_store = create_event_store(f"sqlite:///{tmp_path / 'events.db'}")
    yield sqlite_store
    assert isinstance(sqlite_store, SqliteEventStore)
    sqlite_store.close()


def stored_ids(store: EventStore, user_id: str = "local") -> list[str]:
    return [event.id for event in store.query(EVERYTHING, user_id=user_id)]


def ids(events: list[Event]) -> list[str]:
    return [event.id for event in events]


def test_event_removed_at_the_source_disappears(store: EventStore) -> None:
    store.upsert([make_event(id="kept", start=NOON), make_event(id="gone", start=NOON)])
    store.replace("canvas", DAY, [make_event(id="kept", start=NOON)])
    assert stored_ids(store) == ["kept"]


def test_replacing_with_nothing_clears_the_source_in_the_window(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON)])
    assert store.replace("canvas", DAY, []) == 0
    assert stored_ids(store) == []


def test_moved_event_is_updated_in_place(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON, title="old")])
    store.replace("canvas", DAY, [make_event(id="a", start=NOON + timedelta(hours=3), title="new")])
    (event,) = store.query(EVERYTHING)
    assert (event.title, event.start) == ("new", NOON + timedelta(hours=3))


def test_event_moved_out_of_the_window_follows_the_source(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON)])
    store.replace("canvas", DAY, [make_event(id="a", start=NEXT_WEEK)])
    assert store.query(DAY) == []
    assert stored_ids(store) == ["a"]


def test_event_moved_into_the_window_is_stored(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NEXT_WEEK)])
    store.replace("canvas", DAY, [make_event(id="a", start=NOON)])
    assert ids(store.query(DAY)) == ["a"]


def test_new_event_is_added(store: EventStore) -> None:
    store.replace("canvas", DAY, [make_event(id="new", start=NOON)])
    assert stored_ids(store) == ["new"]


def test_replace_returns_the_number_of_events_written(store: EventStore) -> None:
    store.upsert([make_event(id="old", start=NOON)])
    written = store.replace(
        "canvas", DAY, [make_event(id="a", start=NOON), make_event(id="b", start=NOON)]
    )
    assert written == 2


def test_duplicate_ids_in_one_replace_count_once_and_last_wins(store: EventStore) -> None:
    written = store.replace(
        "canvas",
        DAY,
        [
            make_event(id="a", start=NOON, title="first"),
            make_event(id="a", start=NOON, title="last"),
        ],
    )
    (event,) = store.query(DAY)
    assert (written, event.title) == (1, "last")


def test_event_outside_the_window_is_not_pruned(store: EventStore) -> None:
    store.upsert([make_event(id="later", start=NEXT_WEEK), make_event(id="in", start=NOON)])
    store.replace("canvas", DAY, [])
    assert stored_ids(store) == ["later"]


def test_window_start_is_inclusive_and_end_is_exclusive_when_pruning(store: EventStore) -> None:
    store.upsert(
        [make_event(id="at-start", start=DAY.start), make_event(id="at-end", start=DAY.end)]
    )
    store.replace("canvas", DAY, [])
    assert stored_ids(store) == ["at-end"]


def test_span_overlapping_the_window_is_pruned(store: EventStore) -> None:
    store.upsert([make_event(id="span", start=DAY.start - timedelta(days=2), end=NOON)])
    store.replace("canvas", DAY, [])
    assert stored_ids(store) == []


def test_span_ending_at_the_window_start_is_not_pruned(store: EventStore) -> None:
    store.upsert([make_event(id="span", start=DAY.start - timedelta(hours=1), end=DAY.start)])
    store.replace("canvas", DAY, [])
    assert stored_ids(store) == ["span"]


def test_assignment_is_pruned_by_its_due_date(store: EventStore) -> None:
    store.upsert([make_event(id="hw", kind="assignment", due=NOON)])
    store.replace("canvas", DAY, [])
    assert stored_ids(store) == []


def test_other_sources_are_untouched(store: EventStore) -> None:
    store.upsert([make_event(id="mine", source="canvas", start=NOON)])
    store.upsert([make_event(id="theirs", source="gmail", start=NOON)])
    store.replace("canvas", DAY, [])
    assert stored_ids(store) == ["theirs"]


def test_other_users_are_untouched(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON)])
    store.upsert([make_event(id="a", user_id="alice", start=NOON)], user_id="alice")
    store.replace("canvas", DAY, [])
    assert stored_ids(store, "alice") == ["a"]


def test_replace_for_a_user_writes_that_users_events(store: EventStore) -> None:
    store.replace("canvas", DAY, [make_event(id="a", user_id="alice", start=NOON)], user_id="alice")
    assert (stored_ids(store), stored_ids(store, "alice")) == ([], ["a"])


def test_undated_events_are_untouched(store: EventStore) -> None:
    store.upsert([make_event(id="undated"), make_event(id="end-only", end=NOON)])
    store.replace("canvas", DAY, [])
    assert store.delete_source("canvas") == 2


def test_an_undated_event_in_the_new_batch_is_stored_but_never_appears(store: EventStore) -> None:
    written = store.replace("canvas", DAY, [make_event(id="undated")])
    assert (written, stored_ids(store)) == (1, [])


def test_event_for_another_user_is_rejected_and_the_old_events_remain(store: EventStore) -> None:
    store.upsert([make_event(id="old", start=NOON)])
    with pytest.raises(ValueError, match="user_id"):
        store.replace(
            "canvas",
            DAY,
            [make_event(id="new", start=NOON), make_event(id="bad", user_id="alice", start=NOON)],
        )
    assert stored_ids(store) == ["old"]


def test_event_of_another_source_is_rejected_and_the_old_events_remain(store: EventStore) -> None:
    store.upsert([make_event(id="old", start=NOON)])
    with pytest.raises(ValueError, match="source"):
        store.replace(
            "canvas",
            DAY,
            [make_event(id="new", start=NOON), make_event(id="bad", source="gmail", start=NOON)],
        )
    assert stored_ids(store) == ["old"]


def test_delete_source_removes_dated_and_undated_events_of_that_source(store: EventStore) -> None:
    store.upsert(
        [
            make_event(id="dated", start=NOON),
            make_event(id="far", start=NEXT_WEEK + timedelta(days=300)),
            make_event(id="undated"),
        ]
    )
    deleted = store.delete_source("canvas")
    assert (deleted, store.query(EVERYTHING)) == (3, [])


def test_delete_source_leaves_other_sources(store: EventStore) -> None:
    store.upsert([make_event(id="mine", source="canvas", start=NOON)])
    store.upsert([make_event(id="theirs", source="gmail", start=NOON)])
    store.delete_source("canvas")
    assert stored_ids(store) == ["theirs"]


def test_delete_source_leaves_other_users(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON)])
    store.upsert([make_event(id="a", user_id="alice", start=NOON)], user_id="alice")
    store.delete_source("canvas", user_id="alice")
    assert (stored_ids(store), stored_ids(store, "alice")) == (["a"], [])


def test_delete_source_with_nothing_stored_is_not_an_error(store: EventStore) -> None:
    assert store.delete_source("canvas") == 0
