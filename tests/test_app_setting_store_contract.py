"""One behavioural suite for every AppSettingStore: the in-memory fake and SQLite must agree."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from command_center.core.ports import AppSettingStore
from command_center.storage.sqlite_app_settings import (
    SqliteAppSettingStore,
    create_app_setting_store,
)
from fakes import InMemoryAppSettingStore


def check_missing_key_is_none(store: AppSettingStore) -> None:
    assert store.get("summary.enabled") is None


def check_set_then_get(store: AppSettingStore) -> None:
    store.set("summary.provider", "gemini")
    assert store.get("summary.provider") == "gemini"


def check_set_replaces(store: AppSettingStore) -> None:
    store.set("summary.provider", "gemini")
    store.set("summary.provider", "none")
    assert store.get("summary.provider") == "none"


def check_users_are_separate(store: AppSettingStore) -> None:
    store.set("summary.provider", "gemini", user_id="alice")
    store.set("summary.provider", "none", user_id="bob")
    assert store.get("summary.provider", user_id="alice") == "gemini"
    assert store.get("summary.provider", user_id="bob") == "none"
    assert store.get("summary.provider") is None


def check_keys_are_separate(store: AppSettingStore) -> None:
    store.set("summary.provider", "gemini")
    store.set("summary.enabled", "true")
    assert store.get("summary.provider") == "gemini"
    assert store.get("summary.enabled") == "true"


def check_long_value_round_trips(store: AppSettingStore) -> None:
    value = "x" * 500
    store.set("note", value)
    assert store.get("note") == value


CHECKS: list[Callable[[AppSettingStore], None]] = [
    check_missing_key_is_none,
    check_set_then_get,
    check_set_replaces,
    check_users_are_separate,
    check_keys_are_separate,
    check_long_value_round_trips,
]


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[AppSettingStore]:
    if request.param == "memory":
        yield InMemoryAppSettingStore()
        return
    sqlite_store = create_app_setting_store(f"sqlite:///{tmp_path / 't.db'}")
    yield sqlite_store
    assert isinstance(sqlite_store, SqliteAppSettingStore)
    sqlite_store.close()


@pytest.mark.parametrize("check", CHECKS, ids=lambda check: check.__name__)
def test_contract(store: AppSettingStore, check: Callable[[AppSettingStore], None]) -> None:
    check(store)
