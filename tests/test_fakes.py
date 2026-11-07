"""The shared fakes satisfy the ports and behave like the contract says real stores do."""

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from builders import NAIVE_INSTANTS, NOW, make_event
from command_center.core.ports import Clock, EventStore, SecretStore
from command_center.core.schema import SecretStatus
from command_center.core.windows import TimeWindow
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

DAY = TimeWindow(start=datetime(2026, 11, 7, tzinfo=UTC), end=datetime(2026, 11, 8, tzinfo=UTC))


def test_fake_clock_returns_the_time_it_was_given() -> None:
    clock: Clock = FakeClock(NOW)

    assert clock.now() == NOW


def test_fake_clock_only_moves_when_told() -> None:
    clock = FakeClock(NOW)

    assert clock.now() == clock.now()
    clock.advance(timedelta(hours=2))
    assert clock.now() == NOW + timedelta(hours=2)
    clock.set(NOW)
    assert clock.now() == NOW


def test_fake_clock_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone"):
        FakeClock(datetime(2026, 1, 1))  # noqa: DTZ001


def test_fake_clock_rejects_a_tzinfo_without_a_utc_offset() -> None:
    offsetless = NAIVE_INSTANTS[1]

    with pytest.raises(ValueError, match="timezone"):
        FakeClock(offsetless)


def test_fake_clock_set_rejects_a_tzinfo_without_a_utc_offset() -> None:
    clock = FakeClock(NOW)

    with pytest.raises(ValueError, match="timezone"):
        clock.set(NAIVE_INSTANTS[1])

    assert clock.now() == NOW


# ----------------------------------------------------------------- secrets


def test_secret_store_reports_unset_source_as_empty() -> None:
    store: SecretStore = InMemorySecretStore()

    assert store.get("canvas") == {}
    assert store.status("canvas") == {}


def test_secret_store_keeps_one_value_per_key() -> None:
    store = InMemorySecretStore()
    store.set("caldav", "username", "me@icloud.com")
    store.set("caldav", "password", "fake-abcd-efgh-ijkl")

    assert store.get("caldav") == {"username": "me@icloud.com", "password": "fake-abcd-efgh-ijkl"}


def test_secret_store_status_is_per_key_and_exposes_only_the_last_four_characters() -> None:
    store = InMemorySecretStore()
    store.set("canvas", "token", "fake-abcdefgh1234")
    store.set("canvas", "domain", "short")

    assert store.status("canvas") == {
        "token": SecretStatus(set=True, last4="1234"),
        "domain": SecretStatus(set=True, last4=None),
    }


def test_secret_store_status_hides_last4_below_eight_characters() -> None:
    store = InMemorySecretStore()
    store.set("canvas", "seven", "fake-12")
    store.set("canvas", "eight", "fake-123")

    status = store.status("canvas")

    assert status["seven"] == SecretStatus(set=True, last4=None)
    assert status["eight"] == SecretStatus(set=True, last4="-123")


def test_secret_store_status_never_contains_the_value() -> None:
    store = InMemorySecretStore()
    store.set("canvas", "token", "fake-abcdefgh1234")

    assert "abcdefgh" not in repr(store.status("canvas"))


def test_secret_store_set_overwrites_only_that_key() -> None:
    store = InMemorySecretStore()
    store.set("canvas", "token", "fake-first-0001")
    store.set("canvas", "domain", "canvas.example.edu")
    store.set("canvas", "token", "fake-second-0002")

    assert store.get("canvas") == {"token": "fake-second-0002", "domain": "canvas.example.edu"}


def test_secret_store_get_returns_a_copy() -> None:
    store = InMemorySecretStore()
    store.set("canvas", "token", "fake-12345678")

    cast("dict[str, str]", store.get("canvas")).clear()

    assert store.get("canvas") == {"token": "fake-12345678"}


def test_secret_store_delete_removes_every_key_and_is_idempotent() -> None:
    store = InMemorySecretStore()
    store.set("caldav", "username", "me")
    store.set("caldav", "password", "fake-hunter2-hunter2")
    store.delete("caldav")
    store.delete("caldav")

    assert store.get("caldav") == {}
    assert store.status("caldav") == {}


def test_secret_store_delete_of_an_unknown_source_is_not_an_error() -> None:
    InMemorySecretStore().delete("never-set")


def test_secret_store_isolates_sources_and_users() -> None:
    store = InMemorySecretStore()
    store.set("canvas", "token", "fake-canvas-1111")
    store.set("gmail", "token", "fake-gmail-2222")
    store.set("canvas", "token", "fake-other-3333", user_id="bob")

    assert store.get("canvas") == {"token": "fake-canvas-1111"}
    assert store.get("gmail") == {"token": "fake-gmail-2222"}
    assert store.get("canvas", user_id="bob") == {"token": "fake-other-3333"}
    assert store.status("canvas", user_id="bob")["token"].last4 == "3333"
    store.delete("canvas", user_id="bob")
    assert store.get("canvas") == {"token": "fake-canvas-1111"}
    assert store.get("canvas", user_id="bob") == {}


# ------------------------------------------------------------------ events


def test_event_store_upsert_then_query_returns_events_in_window() -> None:
    store: EventStore = InMemoryEventStore()
    inside = make_event(id="a", start=NOW)
    outside = make_event(id="b", start=NOW + timedelta(days=3))

    assert store.upsert([inside, outside]) == 2
    assert store.query(DAY) == [inside]


def test_event_store_upsert_is_idempotent() -> None:
    store = InMemoryEventStore()
    event = make_event(id="a", start=NOW)

    store.upsert([event])
    store.upsert([event])

    assert store.query(DAY) == [event]


def test_event_store_upsert_replaces_by_id() -> None:
    store = InMemoryEventStore()
    store.upsert([make_event(id="a", start=NOW, title="old")])
    store.upsert([make_event(id="a", start=NOW, title="new")])

    assert [e.title for e in store.query(DAY)] == ["new"]


def test_event_store_upsert_counts_distinct_events_written() -> None:
    store = InMemoryEventStore()
    twice = [make_event(id="a", start=NOW), make_event(id="a", start=NOW, title="dup")]

    assert store.upsert(twice) == 1
    assert store.upsert([]) == 0


def test_event_store_filters_by_kind() -> None:
    store = InMemoryEventStore()
    meeting = make_event(id="m", kind="event", start=NOW)
    homework = make_event(id="h", kind="assignment", due=NOW)
    store.upsert([meeting, homework])

    assert store.query(DAY, kinds=["assignment"]) == [homework]
    assert store.query(DAY, kinds=["assignment", "event"]) == [homework, meeting]
    assert store.query(DAY, kinds=[]) == []


def test_event_store_places_assignments_by_due_and_spans_by_overlap() -> None:
    store = InMemoryEventStore()
    due_inside = make_event(id="d", kind="assignment", due=NOW)
    spanning = make_event(
        id="s", start=DAY.start - timedelta(days=1), end=DAY.start + timedelta(hours=1)
    )
    ends_at_window_start = make_event(id="e", start=DAY.start - timedelta(hours=2), end=DAY.start)
    undated = make_event(id="u", kind="email")
    store.upsert([due_inside, spanning, ends_at_window_start, undated])

    assert {e.id for e in store.query(DAY)} == {"d", "s"}


def test_event_store_window_is_half_open() -> None:
    store = InMemoryEventStore()
    at_start = make_event(id="a", start=DAY.start)
    at_end = make_event(id="b", start=DAY.end)
    store.upsert([at_start, at_end])

    assert store.query(DAY) == [at_start]


def test_event_store_orders_results_by_time_then_id() -> None:
    store = InMemoryEventStore()
    late = make_event(id="a", start=NOW + timedelta(hours=2))
    early_b = make_event(id="b", start=NOW)
    early_c = make_event(id="c", start=NOW)
    store.upsert([late, early_c, early_b])

    assert [e.id for e in store.query(DAY)] == ["b", "c", "a"]


def test_event_store_isolates_users() -> None:
    store = InMemoryEventStore()
    mine = make_event(id="same", start=NOW, title="mine")
    theirs = make_event(id="same", start=NOW, title="theirs", user_id="bob")
    store.upsert([mine])
    store.upsert([theirs], user_id="bob")

    assert [e.title for e in store.query(DAY)] == ["mine"]
    assert [e.title for e in store.query(DAY, user_id="bob")] == ["theirs"]


def test_event_store_rejects_event_owned_by_another_user() -> None:
    store = InMemoryEventStore()

    with pytest.raises(ValueError, match="user_id"):
        store.upsert([make_event(id="a", user_id="bob")])
