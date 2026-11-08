"""One contract suite for every DeviceStore. Subclass it and override make_store()."""

from datetime import UTC, datetime, timedelta

import pytest

from command_center.core.pairing import Device, RefreshRecord
from command_center.core.ports import DeviceStore

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
TTL = timedelta(minutes=5)
ACCESS = timedelta(minutes=15)


def make_device(device_id: str = "fake-dev-1", created_at: datetime = NOW) -> Device:
    return Device(id=device_id, name="Phone", created_at=created_at, last_seen_at=created_at)


class DeviceStoreContract:
    """Behaviour every DeviceStore must have; hashes are opaque strings to the store."""

    def make_store(self) -> DeviceStore:
        raise NotImplementedError

    @pytest.fixture
    def store(self) -> DeviceStore:
        return self.make_store()

    def _pair(
        self,
        store: DeviceStore,
        device_id: str = "fake-dev-1",
        *,
        refresh: str = "fake-refresh-1",
        access: str = "fake-access-1",
        at: datetime = NOW,
    ) -> None:
        store.add_device(make_device(device_id, at), refresh, access, at + ACCESS)

    # ------------------------------------------------------------ pairing tokens

    def test_take_pairing_succeeds_once_for_a_live_token(self, store: DeviceStore) -> None:
        store.put_pairing("fake-pair-1", NOW + TTL, NOW)
        assert store.take_pairing("fake-pair-1", NOW + timedelta(seconds=1)) is True
        assert store.take_pairing("fake-pair-1", NOW + timedelta(seconds=2)) is False

    def test_take_pairing_fails_for_an_unknown_token(self, store: DeviceStore) -> None:
        assert store.take_pairing("fake-pair-unknown", NOW) is False

    def test_take_pairing_fails_at_and_after_expiry(self, store: DeviceStore) -> None:
        store.put_pairing("fake-pair-1", NOW + TTL, NOW)
        assert store.take_pairing("fake-pair-1", NOW + TTL) is False
        store.put_pairing("fake-pair-2", NOW + TTL, NOW)
        assert store.take_pairing("fake-pair-2", NOW + TTL + timedelta(seconds=1)) is False

    def test_take_pairing_succeeds_just_before_expiry(self, store: DeviceStore) -> None:
        store.put_pairing("fake-pair-1", NOW + TTL, NOW)
        assert store.take_pairing("fake-pair-1", NOW + TTL - timedelta(microseconds=1)) is True

    def test_put_pairing_leaves_only_the_newest_token_live(self, store: DeviceStore) -> None:
        store.put_pairing("fake-pair-1", NOW + TTL, NOW)
        store.put_pairing("fake-pair-2", NOW + TTL, NOW)
        assert store.take_pairing("fake-pair-1", NOW) is False
        assert store.take_pairing("fake-pair-2", NOW) is True

    def test_put_pairing_drops_expired_tokens(self, store: DeviceStore) -> None:
        store.put_pairing("fake-pair-1", NOW + TTL, NOW)
        later = NOW + TTL + timedelta(minutes=1)
        store.put_pairing("fake-pair-2", later + TTL, later)
        assert store.take_pairing("fake-pair-1", NOW) is False

    def test_a_consumed_pairing_token_cannot_be_taken_again_after_a_new_one(
        self, store: DeviceStore
    ) -> None:
        store.put_pairing("fake-pair-1", NOW + TTL, NOW)
        assert store.take_pairing("fake-pair-1", NOW) is True
        store.put_pairing("fake-pair-2", NOW + TTL, NOW)
        assert store.take_pairing("fake-pair-1", NOW) is False

    # ------------------------------------------------------------ devices and access

    def test_add_device_makes_the_access_hash_resolve_until_it_expires(
        self, store: DeviceStore
    ) -> None:
        self._pair(store)
        assert store.device_for_access("fake-access-1", NOW) == "fake-dev-1"
        assert store.device_for_access("fake-access-1", NOW + ACCESS - timedelta(seconds=1)) == (
            "fake-dev-1"
        )
        assert store.device_for_access("fake-access-1", NOW + ACCESS) is None

    def test_device_for_access_is_none_for_an_unknown_hash(self, store: DeviceStore) -> None:
        self._pair(store)
        assert store.device_for_access("fake-access-other", NOW) is None

    def test_a_refresh_hash_is_not_an_access_hash(self, store: DeviceStore) -> None:
        self._pair(store)
        assert store.device_for_access("fake-refresh-1", NOW) is None

    def test_list_devices_is_oldest_first(self, store: DeviceStore) -> None:
        self._pair(store, "fake-dev-b", refresh="r-b", access="a-b", at=NOW + timedelta(hours=2))
        self._pair(store, "fake-dev-a", refresh="r-a", access="a-a", at=NOW)
        self._pair(store, "fake-dev-c", refresh="r-c", access="a-c", at=NOW + timedelta(hours=1))
        assert [d.id for d in store.list_devices()] == ["fake-dev-a", "fake-dev-c", "fake-dev-b"]

    def test_list_devices_round_trips_the_device(self, store: DeviceStore) -> None:
        self._pair(store)
        assert store.list_devices() == [make_device()]

    def test_list_devices_is_empty_for_a_new_store(self, store: DeviceStore) -> None:
        assert store.list_devices() == []

    # ------------------------------------------------------------ refresh

    def test_refresh_record_reports_a_current_refresh_hash(self, store: DeviceStore) -> None:
        self._pair(store)
        assert store.refresh_record("fake-refresh-1") == RefreshRecord(
            device_id="fake-dev-1", superseded=False
        )

    def test_refresh_record_is_none_for_an_unknown_hash(self, store: DeviceStore) -> None:
        self._pair(store)
        assert store.refresh_record("fake-refresh-unknown") is None

    def test_rotate_refresh_returns_the_device_id_and_swaps_the_credentials(
        self, store: DeviceStore
    ) -> None:
        self._pair(store)
        later = NOW + timedelta(minutes=20)
        device_id = store.rotate_refresh(
            "fake-refresh-1", "fake-refresh-2", "fake-access-2", later + ACCESS, later
        )
        assert device_id == "fake-dev-1"
        assert store.refresh_record("fake-refresh-1") == RefreshRecord(
            device_id="fake-dev-1", superseded=True
        )
        assert store.refresh_record("fake-refresh-2") == RefreshRecord(
            device_id="fake-dev-1", superseded=False
        )
        assert store.device_for_access("fake-access-2", later) == "fake-dev-1"

    def test_rotate_refresh_drops_the_old_access_hash(self, store: DeviceStore) -> None:
        self._pair(store)
        store.rotate_refresh("fake-refresh-1", "fake-refresh-2", "fake-access-2", NOW + ACCESS, NOW)
        assert store.device_for_access("fake-access-1", NOW) is None

    def test_rotate_refresh_sets_last_seen_at(self, store: DeviceStore) -> None:
        self._pair(store)
        later = NOW + timedelta(minutes=20)
        store.rotate_refresh("fake-refresh-1", "fake-refresh-2", "fake-access-2", later, later)
        (device,) = store.list_devices()
        assert device.last_seen_at == later
        assert device.created_at == NOW

    def test_rotate_refresh_with_a_superseded_hash_changes_nothing(
        self, store: DeviceStore
    ) -> None:
        self._pair(store)
        store.rotate_refresh("fake-refresh-1", "fake-refresh-2", "fake-access-2", NOW + ACCESS, NOW)
        later = NOW + timedelta(hours=1)
        result = store.rotate_refresh(
            "fake-refresh-1", "fake-refresh-3", "fake-access-3", later + ACCESS, later
        )
        assert result is None
        assert store.refresh_record("fake-refresh-3") is None
        assert store.refresh_record("fake-refresh-2") == RefreshRecord(
            device_id="fake-dev-1", superseded=False
        )
        assert store.device_for_access("fake-access-3", later) is None
        assert store.device_for_access("fake-access-2", NOW) == "fake-dev-1"
        (device,) = store.list_devices()
        assert device.last_seen_at == NOW

    def test_rotate_refresh_with_an_unknown_hash_changes_nothing(self, store: DeviceStore) -> None:
        self._pair(store)
        result = store.rotate_refresh(
            "fake-refresh-unknown", "fake-refresh-2", "fake-access-2", NOW + ACCESS, NOW
        )
        assert result is None
        assert store.refresh_record("fake-refresh-2") is None
        assert store.device_for_access("fake-access-1", NOW) == "fake-dev-1"

    def test_rotate_refresh_only_touches_its_own_device(self, store: DeviceStore) -> None:
        self._pair(store, "fake-dev-1", refresh="r-1", access="a-1")
        self._pair(store, "fake-dev-2", refresh="r-2", access="a-2")
        store.rotate_refresh("r-1", "r-1b", "a-1b", NOW + ACCESS, NOW)
        assert store.device_for_access("a-2", NOW) == "fake-dev-2"
        assert store.refresh_record("r-2") == RefreshRecord(
            device_id="fake-dev-2", superseded=False
        )

    # ------------------------------------------------------------ removal

    def test_remove_device_deletes_every_credential_of_it(self, store: DeviceStore) -> None:
        self._pair(store)
        store.rotate_refresh("fake-refresh-1", "fake-refresh-2", "fake-access-2", NOW + ACCESS, NOW)
        assert store.remove_device("fake-dev-1") is True
        assert store.list_devices() == []
        assert store.refresh_record("fake-refresh-1") is None
        assert store.refresh_record("fake-refresh-2") is None
        assert store.device_for_access("fake-access-2", NOW) is None
        assert (
            store.rotate_refresh("fake-refresh-2", "fake-refresh-3", "fake-access-3", NOW, NOW)
            is None
        )

    def test_remove_device_returns_false_for_an_unknown_device(self, store: DeviceStore) -> None:
        assert store.remove_device("fake-dev-missing") is False

    def test_remove_device_leaves_other_devices_working(self, store: DeviceStore) -> None:
        self._pair(store, "fake-dev-1", refresh="r-1", access="a-1")
        self._pair(store, "fake-dev-2", refresh="r-2", access="a-2")
        store.remove_device("fake-dev-1")
        assert [d.id for d in store.list_devices()] == ["fake-dev-2"]
        assert store.device_for_access("a-2", NOW) == "fake-dev-2"
        assert store.device_for_access("a-1", NOW) is None
