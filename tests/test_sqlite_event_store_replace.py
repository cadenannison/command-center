"""SQLite-specific atomicity of replace; the matching rules live in the replace contract suite."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic_core import PydanticSerializationError

from builders import make_event
from command_center.core.windows import TimeWindow
from command_center.storage.sqlite import create_event_store

NOON = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
DAY = TimeWindow(start=NOON - timedelta(hours=12), end=NOON + timedelta(hours=12))


def test_a_failure_while_writing_rolls_the_delete_back(tmp_path: Path) -> None:
    store = create_event_store(f"sqlite:///{tmp_path / 'events.db'}")
    store.upsert([make_event(id="old", start=NOON)])
    unserialisable = make_event(id="new", start=NOON, raw={"value": object()})

    with pytest.raises(PydanticSerializationError):
        store.replace("canvas", DAY, [unserialisable])

    assert [e.id for e in store.query(DAY)] == ["old"]
    store.close()


def test_delete_source_counts_only_the_rows_it_removed(tmp_path: Path) -> None:
    store = create_event_store(f"sqlite:///{tmp_path / 'events.db'}")
    store.upsert([make_event(id="a", start=NOON), make_event(id="b", source="gmail", start=NOON)])

    assert store.delete_source("canvas") == 1
    store.close()
