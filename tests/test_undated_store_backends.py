"""EventStore.undated_open on SQLite and Postgres (CC_TEST_POSTGRES_URL), decision 0372.

Each test gets an empty database (a schema of its own on Postgres, dropped afterwards), so rows
never leak between tests or into a shared server. The in-memory fake is the reference for limit.
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from builders import NOW, make_event
from command_center.core.schema import Event, EventKind
from command_center.storage.sqlite import SqliteEventStore
from fakes import InMemoryEventStore
from sink_support import DATABASES, open_engine, open_stores

OPEN_KINDS: list[EventKind] = ["task", "assignment"]
MINUTE = timedelta(minutes=1)


@pytest.fixture(params=DATABASES)
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[SqliteEventStore]:
    for engine in open_engine(request.param, tmp_path):
        yield open_stores(engine).events


def task(id_: str, **overrides: object) -> Event:
    return make_event(id=id_, kind="task", source="local", **overrides)


def ids(events: list[Event]) -> list[str]:
    return [e.id for e in events]


def test_only_open_task_and_assignment_kinds_are_returned(store: SqliteEventStore) -> None:
    store.upsert(
        [
            task("t"),
            make_event(id="a", kind="assignment", source="canvas"),
            make_event(id="e", kind="event"),
            make_event(id="m", kind="email", source="gmail", status="owed"),
            make_event(id="w", kind="weather"),
        ]
    )

    assert sorted(ids(store.undated_open(OPEN_KINDS, 10))) == ["a", "t"]


def test_the_assignment_kind_alone_returns_only_assignments(store: SqliteEventStore) -> None:
    store.upsert([task("t"), make_event(id="a", kind="assignment", source="canvas")])

    assert ids(store.undated_open(["assignment"], 10)) == ["a"]


def test_done_rows_are_excluded(store: SqliteEventStore) -> None:
    store.upsert([task("done", status="done"), task("open", status="open")])

    assert ids(store.undated_open(OPEN_KINDS, 10)) == ["open"]


def test_a_null_status_counts_as_open(store: SqliteEventStore) -> None:
    store.upsert([task("none", status=None)])

    assert ids(store.undated_open(OPEN_KINDS, 10)) == ["none"]


def test_rows_with_a_start_are_excluded(store: SqliteEventStore) -> None:
    store.upsert([task("started", start=NOW + MINUTE), task("undated")])

    assert ids(store.undated_open(OPEN_KINDS, 10)) == ["undated"]


def test_rows_with_a_due_time_are_excluded(store: SqliteEventStore) -> None:
    store.upsert([task("due", due=NOW + MINUTE), task("undated")])

    assert ids(store.undated_open(OPEN_KINDS, 10)) == ["undated"]


def test_newest_fetched_at_comes_first(store: SqliteEventStore) -> None:
    store.upsert(
        [
            task("old", fetched_at=NOW),
            task("new", fetched_at=NOW + 2 * MINUTE),
            task("mid", fetched_at=NOW + MINUTE),
        ]
    )

    assert ids(store.undated_open(OPEN_KINDS, 10)) == ["new", "mid", "old"]


def test_equal_fetched_at_is_ordered_by_id_ascending(store: SqliteEventStore) -> None:
    store.upsert([task("b"), task("c"), task("a"), task("newer", fetched_at=NOW + MINUTE)])

    assert ids(store.undated_open(OPEN_KINDS, 10)) == ["newer", "a", "b", "c"]


def test_the_limit_is_honored_after_ordering(store: SqliteEventStore) -> None:
    store.upsert([task(f"t{n}", fetched_at=NOW + n * MINUTE) for n in range(5)])

    assert ids(store.undated_open(OPEN_KINDS, 2)) == ["t4", "t3"]


@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_below_one_returns_nothing_like_the_fake(
    store: SqliteEventStore, limit: int
) -> None:
    events = [task("a"), task("b")]
    store.upsert(events)
    fake = InMemoryEventStore()
    fake.upsert(events)

    assert store.undated_open(OPEN_KINDS, limit) == fake.undated_open(OPEN_KINDS, limit) == []


def test_another_users_rows_never_appear(store: SqliteEventStore) -> None:
    store.upsert([task("mine")])
    store.upsert([task("theirs", user_id="alice")], user_id="alice")

    assert ids(store.undated_open(OPEN_KINDS, 10)) == ["mine"]
    assert ids(store.undated_open(OPEN_KINDS, 10, user_id="alice")) == ["theirs"]
    assert store.undated_open(OPEN_KINDS, 10, user_id="nobody") == []
