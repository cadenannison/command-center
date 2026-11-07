"""One behavioural suite for every EventStore: the in-memory fake and SQLite must agree."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
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
NOON = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[EventStore]:
    if request.param == "memory":
        yield InMemoryEventStore()
        return
    sqlite_store = create_event_store(f"sqlite:///{tmp_path / 'events.db'}")
    yield sqlite_store
    assert isinstance(sqlite_store, SqliteEventStore)
    sqlite_store.close()


def ids(events: list[Event]) -> list[str]:
    return [event.id for event in events]


def test_start_places_event_in_window(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON)])
    assert ids(store.query(DAY)) == ["a"]


def test_due_places_event_in_window_when_there_is_no_start(store: EventStore) -> None:
    store.upsert([make_event(id="a", kind="assignment", due=NOON)])
    assert ids(store.query(DAY)) == ["a"]


def test_start_wins_over_due_for_placement(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON, due=NOON + timedelta(days=3))])
    assert ids(store.query(DAY)) == ["a"]


def test_start_wins_over_due_so_a_later_window_misses_it(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON, due=NOON + timedelta(days=3))])
    later = TimeWindow(start=DAY.start + timedelta(days=3), end=DAY.end + timedelta(days=3))
    assert store.query(later) == []


def test_undated_event_never_matches(store: EventStore) -> None:
    store.upsert([make_event(id="a")])
    assert store.query(DAY) == []


def test_event_with_only_an_end_is_undated(store: EventStore) -> None:
    store.upsert([make_event(id="a", end=NOON)])
    assert store.query(DAY) == []


def test_window_start_is_inclusive(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=DAY.start)])
    assert ids(store.query(DAY)) == ["a"]


def test_window_end_is_exclusive(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=DAY.end)])
    assert store.query(DAY) == []


def test_span_starting_before_window_matches_when_it_overlaps(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=DAY.start - timedelta(hours=2), end=NOON)])
    assert ids(store.query(DAY)) == ["a"]


def test_span_starting_inside_and_ending_after_window_matches(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON, end=DAY.end + timedelta(hours=5))])
    assert ids(store.query(DAY)) == ["a"]


def test_span_covering_whole_window_matches(store: EventStore) -> None:
    store.upsert(
        [make_event(id="a", start=DAY.start - timedelta(days=1), end=DAY.end + timedelta(days=1))]
    )
    assert ids(store.query(DAY)) == ["a"]


def test_span_ending_exactly_at_window_start_does_not_match(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=DAY.start - timedelta(hours=1), end=DAY.start)])
    assert store.query(DAY) == []


def test_span_starting_exactly_at_window_end_does_not_match(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=DAY.end, end=DAY.end + timedelta(hours=1))])
    assert store.query(DAY) == []


def test_event_whose_end_equals_start_is_a_point_not_a_span(store: EventStore) -> None:
    before = TimeWindow(start=DAY.start - timedelta(days=1), end=DAY.start)
    store.upsert([make_event(id="a", start=DAY.start, end=DAY.start)])
    assert store.query(before) == []


def test_due_with_later_end_is_a_span(store: EventStore) -> None:
    store.upsert(
        [make_event(id="a", kind="assignment", due=DAY.start - timedelta(hours=1), end=NOON)]
    )
    assert ids(store.query(DAY)) == ["a"]


def test_results_are_ordered_by_time_then_id(store: EventStore) -> None:
    store.upsert(
        [
            make_event(id="b", start=NOON),
            make_event(id="a", start=NOON),
            make_event(id="z", start=NOON - timedelta(hours=1)),
        ]
    )
    assert ids(store.query(DAY)) == ["z", "a", "b"]


def test_ordering_compares_instants_across_timezones(store: EventStore) -> None:
    plus_five = timezone(timedelta(hours=5))
    # 13:00+05:00 is 08:00 UTC, earlier than 09:00 UTC despite the larger wall-clock hour.
    store.upsert(
        [
            make_event(id="utc", start=datetime(2026, 11, 7, 9, 0, tzinfo=UTC)),
            make_event(id="east", start=datetime(2026, 11, 7, 13, 0, tzinfo=plus_five)),
        ]
    )
    assert ids(store.query(DAY)) == ["east", "utc"]


def test_kinds_filter_keeps_only_those_kinds(store: EventStore) -> None:
    store.upsert(
        [
            make_event(id="a", kind="event", start=NOON),
            make_event(id="b", kind="email", start=NOON),
            make_event(id="c", kind="weather", start=NOON),
        ]
    )
    assert ids(store.query(DAY, {"event", "weather"})) == ["a", "c"]


def test_empty_kinds_filter_matches_nothing(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON)])
    assert store.query(DAY, set()) == []


def test_upsert_returns_number_of_events_written(store: EventStore) -> None:
    assert store.upsert([make_event(id="a"), make_event(id="b")]) == 2


def test_upsert_of_empty_batch_writes_nothing(store: EventStore) -> None:
    assert store.upsert([]) == 0


def test_upserting_same_batch_twice_is_idempotent(store: EventStore) -> None:
    batch = [make_event(id="a", start=NOON), make_event(id="b", start=NOON)]
    store.upsert(batch)
    store.upsert(batch)
    assert ids(store.query(DAY)) == ["a", "b"]


def test_upsert_replaces_an_existing_event(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON, title="old", status="x")])
    store.upsert([make_event(id="a", start=NOON, title="new", status=None)])
    (event,) = store.query(DAY)
    assert (event.title, event.status) == ("new", None)


def test_upsert_can_move_an_event_out_of_a_window(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON)])
    store.upsert([make_event(id="a", start=NOON + timedelta(days=2))])
    assert store.query(DAY) == []


def test_duplicate_ids_in_one_batch_count_once_and_last_wins(store: EventStore) -> None:
    written = store.upsert([make_event(id="a", title="first"), make_event(id="a", title="last")])
    store.upsert([make_event(id="a", start=NOON, title="last")])
    (event,) = store.query(DAY)
    assert (written, event.title) == (1, "last")


def test_upsert_rejects_event_for_another_user(store: EventStore) -> None:
    with pytest.raises(ValueError, match="user_id"):
        store.upsert([make_event(id="a", user_id="alice")])


def test_rejected_batch_writes_nothing(store: EventStore) -> None:
    with pytest.raises(ValueError, match="user_id"):
        store.upsert([make_event(id="a", start=NOON), make_event(id="b", user_id="alice")])
    assert store.query(DAY) == []


def test_users_do_not_see_each_others_events(store: EventStore) -> None:
    store.upsert([make_event(id="a", user_id="alice", start=NOON)], user_id="alice")
    assert store.query(DAY) == []


def test_same_id_for_two_users_are_separate_events(store: EventStore) -> None:
    store.upsert([make_event(id="a", user_id="alice", title="A", start=NOON)], user_id="alice")
    store.upsert([make_event(id="a", user_id="bob", title="B", start=NOON)], user_id="bob")
    assert [e.title for e in store.query(DAY, user_id="alice")] == ["A"]


def test_events_round_trip_with_every_field(store: EventStore) -> None:
    event = make_event(
        id="a",
        kind="assignment",
        title="Essay",
        start=NOON,
        end=NOON + timedelta(hours=1),
        due=NOON + timedelta(hours=2),
        urgency=0,
        link="https://example.com/a",
        status="open",
        raw={"n": 1, "nested": {"k": ["v", None, 2.5]}},
    )
    store.upsert([event])
    assert store.query(DAY) == [event]


def test_returned_datetimes_are_timezone_aware(store: EventStore) -> None:
    store.upsert([make_event(id="a", start=NOON, end=NOON + timedelta(hours=1), due=NOON)])
    (event,) = store.query(DAY)
    moments = (event.start, event.end, event.due, event.fetched_at)
    assert all(moment is not None and moment.utcoffset() is not None for moment in moments)
