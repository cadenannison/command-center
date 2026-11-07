"""SQLite-specific behaviour; the matching rules live in test_event_store_contract.py."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

from builders import make_event
from command_center.core.windows import TimeWindow
from command_center.storage.sqlite import create_event_store

NOON = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
DAY = TimeWindow(start=NOON - timedelta(hours=12), end=NOON + timedelta(hours=12))


def test_events_survive_reopening_the_database(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'events.db'}"
    first = create_event_store(url)
    first.upsert([make_event(id="a", start=NOON)])
    first.close()
    second = create_event_store(url)
    assert [e.id for e in second.query(DAY)] == ["a"]
    second.close()


def test_missing_parent_directory_is_created(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "events.db"
    store = create_event_store(f"sqlite:///{path}")
    store.close()
    assert path.exists()


def test_in_memory_url_is_supported() -> None:
    store = create_event_store("sqlite://")
    store.upsert([make_event(id="a", start=NOON)])
    assert [e.id for e in store.query(DAY)] == ["a"]
    store.close()


def test_instants_are_stored_in_utc(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    store = create_event_store(f"sqlite:///{path}")
    mountain = timezone(timedelta(hours=-7))
    store.upsert([make_event(id="a", start=datetime(2026, 11, 7, 5, 0, tzinfo=mountain))])
    store.close()
    with create_engine(f"sqlite:///{path}").connect() as connection:
        stored = connection.execute(text("SELECT start FROM events")).scalar_one()
    assert stored.startswith("2026-11-07 12:00:00")


def test_returned_datetimes_are_in_utc_with_the_same_instant(tmp_path: Path) -> None:
    store = create_event_store(f"sqlite:///{tmp_path / 'events.db'}")
    mountain = timezone(timedelta(hours=-7))
    start = datetime(2026, 11, 7, 5, 0, tzinfo=mountain)
    store.upsert([make_event(id="a", start=start)])
    (event,) = store.query(DAY)
    store.close()
    assert event.start == start
    assert event.start is not None
    assert event.start.utcoffset() == timedelta(0)


def test_window_in_another_timezone_selects_by_instant(tmp_path: Path) -> None:
    store = create_event_store(f"sqlite:///{tmp_path / 'events.db'}")
    mountain = timezone(timedelta(hours=-7))
    store.upsert([make_event(id="a", start=NOON)])
    window = TimeWindow(
        start=datetime(2026, 11, 7, 5, 0, tzinfo=mountain),  # 12:00 UTC, inclusive
        end=datetime(2026, 11, 7, 6, 0, tzinfo=mountain),
    )
    assert [e.id for e in store.query(window)] == ["a"]
    store.close()


def test_non_json_raw_values_are_stored_as_json(tmp_path: Path) -> None:
    store = create_event_store(f"sqlite:///{tmp_path / 'events.db'}")
    store.upsert([make_event(id="a", start=NOON, raw={"when": NOON})])
    (event,) = store.query(DAY)
    store.close()
    assert event.raw == {"when": "2026-11-07T12:00:00Z"}
