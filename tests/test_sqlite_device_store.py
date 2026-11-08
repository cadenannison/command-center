"""SqliteDeviceStore keeps the shared DeviceStore contract and survives a restart."""

import sqlite3
from pathlib import Path

from command_center.core.ports import DeviceStore
from command_center.storage.sqlite_devices import create_device_store
from device_store_contract import ACCESS, NOW, TTL, DeviceStoreContract, make_device


class TestSqliteDeviceStore(DeviceStoreContract):
    def make_store(self) -> DeviceStore:
        return create_device_store("sqlite://")


def test_credentials_survive_reopening_the_database(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'cc.db'}"
    first = create_device_store(url)
    first.add_device(make_device(), "fake-refresh-1", "fake-access-1", NOW + ACCESS)
    first.close()
    second = create_device_store(url)
    assert second.device_for_access("fake-access-1", NOW) == "fake-dev-1"
    assert [d.id for d in second.list_devices()] == ["fake-dev-1"]


def test_a_pairing_token_survives_reopening_and_still_works_once(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'cc.db'}"
    first = create_device_store(url)
    first.put_pairing("fake-pair-1", NOW + TTL, NOW)
    first.close()
    second = create_device_store(url)
    assert second.take_pairing("fake-pair-1", NOW) is True
    assert second.take_pairing("fake-pair-1", NOW) is False


def test_the_database_file_holds_only_the_digests_it_was_given(tmp_path: Path) -> None:
    path = tmp_path / "cc.db"
    store = create_device_store(f"sqlite:///{path}")
    store.put_pairing("fake-pair-digest", NOW + TTL, NOW)
    store.add_device(make_device(), "fake-refresh-digest", "fake-access-digest", NOW + ACCESS)
    store.close()
    with sqlite3.connect(path) as db:
        dump = "\n".join(db.iterdump())
    assert "fake-pair-digest" in dump
    assert "fake-refresh-digest" in dump
    assert "fake-access-digest" in dump
    assert "token_hash" in dump  # the column names say these are digests


def test_removing_a_device_leaves_no_credential_rows(tmp_path: Path) -> None:
    path = tmp_path / "cc.db"
    store = create_device_store(f"sqlite:///{path}")
    store.add_device(make_device(), "fake-refresh-1", "fake-access-1", NOW + ACCESS)
    store.rotate_refresh("fake-refresh-1", "fake-refresh-2", "fake-access-2", NOW + ACCESS, NOW)
    store.remove_device("fake-dev-1")
    store.close()
    with sqlite3.connect(path) as db:
        count = db.execute("select count(*) from device_credentials").fetchone()[0]
    assert count == 0


def _store_without_its_device() -> DeviceStore:
    store = create_device_store("sqlite://")
    store.add_device(make_device(), "fake-refresh-1", "fake-access-1", NOW + ACCESS)
    engine = store._engine  # type: ignore[attr-defined]  # noqa: SLF001 - simulating a lost race
    with engine.begin() as connection:
        connection.exec_driver_sql("delete from devices")
    return store


def test_an_access_credential_whose_device_is_gone_does_not_authenticate() -> None:
    store = _store_without_its_device()
    assert store.device_for_access("fake-access-1", NOW) is None


def test_a_refresh_credential_whose_device_is_gone_does_not_rotate() -> None:
    store = _store_without_its_device()
    rotated = store.rotate_refresh(
        "fake-refresh-1", "fake-refresh-2", "fake-access-2", NOW + ACCESS, NOW
    )
    assert rotated is None
