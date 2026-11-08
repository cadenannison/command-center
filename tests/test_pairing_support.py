"""The pairing fakes obey their contracts (the DeviceStore suite is shared with SQLite)."""

from command_center.core.pairing import hash_token, is_plausible_token
from command_center.core.ports import DeviceStore
from device_store_contract import ACCESS, NOW, TTL, DeviceStoreContract, make_device
from pairing_support import FakeTokenSource, InMemoryDeviceStore


class TestInMemoryDeviceStore(DeviceStoreContract):
    def make_store(self) -> DeviceStore:
        return InMemoryDeviceStore()


def test_in_memory_store_lookups_count_the_four_lookup_methods() -> None:
    store = InMemoryDeviceStore()
    assert store.lookups == 0
    store.put_pairing("fake-pair-1", NOW + TTL, NOW)
    store.add_device(make_device(), "fake-refresh-1", "fake-access-1", NOW + ACCESS)
    assert store.lookups == 0
    store.take_pairing("fake-pair-1", NOW)
    store.rotate_refresh("fake-refresh-1", "fake-refresh-2", "fake-access-2", NOW + ACCESS, NOW)
    store.refresh_record("fake-refresh-2")
    store.device_for_access("fake-access-2", NOW)
    assert store.lookups == 4


def test_in_memory_store_exposes_its_hashes() -> None:
    store = InMemoryDeviceStore()
    store.put_pairing("fake-pair-1", NOW + TTL, NOW)
    assert store.pairing_hashes() == {"fake-pair-1"}
    store.take_pairing("fake-pair-1", NOW)
    assert store.pairing_hashes() == set()
    store.add_device(make_device(), "fake-refresh-1", "fake-access-1", NOW + ACCESS)
    store.put_pairing("fake-pair-2", NOW + TTL, NOW)
    assert store.all_hashes() == {"fake-pair-2", "fake-refresh-1", "fake-access-1"}
    store.rotate_refresh("fake-refresh-1", "fake-refresh-2", "fake-access-2", NOW + ACCESS, NOW)
    assert store.all_hashes() == {
        "fake-pair-2",
        "fake-refresh-1",
        "fake-refresh-2",
        "fake-access-2",
    }


def test_fake_token_source_tokens_are_unique_plausible_and_hashable() -> None:
    source = FakeTokenSource()
    tokens = [source.new_token(16) for _ in range(50)]
    assert len(set(tokens)) == 50
    assert all(is_plausible_token(t) for t in tokens)
    assert len({hash_token(t) for t in tokens}) == 50
    assert all(t.startswith("fake-") for t in tokens)


def test_fake_token_source_is_deterministic_and_records_requested_sizes() -> None:
    first, second = FakeTokenSource(), FakeTokenSource()
    assert first.requested == []
    assert [first.new_token(16), first.new_token(32)] == [
        second.new_token(16),
        second.new_token(32),
    ]
    assert first.requested == [16, 32]
