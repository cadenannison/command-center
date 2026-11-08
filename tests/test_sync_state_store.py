"""SyncStateStore: the in-memory fake and the SQLite store keep the same rules."""

from collections.abc import Callable
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from command_center.core.ports import SyncStateStore
from command_center.core.sync_state import SyncState
from command_center.storage.sqlite_states import create_sync_state_store
from queue_support import START
from worker_support import InMemorySyncStateStore


def state(source: str = "canvas", status: str = "ok", message: str = "Synced 1 items") -> SyncState:
    return SyncState.model_validate(
        {"source": source, "status": status, "message": message, "at": START}
    )


@pytest.fixture(params=["memory", "sqlite"])
def make(request: pytest.FixtureRequest, tmp_path: Path) -> Callable[[], SyncStateStore]:
    if request.param == "memory":
        shared = InMemorySyncStateStore()
        return lambda: shared
    url = f"sqlite:///{tmp_path / 'states.db'}"
    return lambda: create_sync_state_store(url)


def test_get_of_a_source_never_stored_is_none(make: Callable[[], SyncStateStore]) -> None:
    assert make().get("canvas") is None


def test_put_then_get_round_trips(make: Callable[[], SyncStateStore]) -> None:
    store = make()
    store.put(state())
    assert store.get("canvas") == state()


def test_put_replaces_the_earlier_state(make: Callable[[], SyncStateStore]) -> None:
    store = make()
    store.put(state(status="reconnect", message="Credentials were rejected; reconnect"))
    store.put(state())
    assert store.get("canvas") == state()


def test_states_are_per_source_and_per_user(make: Callable[[], SyncStateStore]) -> None:
    store = make()
    store.put(state("canvas"))
    assert store.get("gmail") is None
    assert store.get("canvas", user_id="other") is None


def test_delete_forgets_the_state_and_a_missing_one_is_not_an_error(
    make: Callable[[], SyncStateStore],
) -> None:
    store = make()
    store.put(state())
    store.delete("canvas")
    store.delete("canvas")
    assert store.get("canvas") is None


def test_a_state_survives_a_second_connection_to_the_same_database(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'states.db'}"
    create_sync_state_store(url).put(state())
    assert create_sync_state_store(url).get("canvas") == state()


def test_the_instant_is_kept_when_it_was_written_in_another_zone(tmp_path: Path) -> None:
    store = create_sync_state_store(f"sqlite:///{tmp_path / 'states.db'}")
    local = START.astimezone(timezone(timedelta(hours=-7)))
    store.put(state().model_copy(update={"at": local}))
    stored = store.get("canvas")
    assert stored is not None
    assert stored.at == START
    assert stored.at.utcoffset() == timedelta(0)
