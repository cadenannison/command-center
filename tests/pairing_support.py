"""Fakes for pairing: a counter-based TokenSource and a faithful in-memory DeviceStore."""

from datetime import datetime

from command_center.core.pairing import Device, RefreshRecord


class FakeTokenSource:
    """A TokenSource handing out unique, plausible, deterministic tokens and recording sizes."""

    def __init__(self) -> None:
        self.requested: list[int] = []
        self._counter = 0

    def new_token(self, num_bytes: int) -> str:
        self.requested.append(num_bytes)
        self._counter += 1
        return f"fake-token-{self._counter:08d}"


class InMemoryDeviceStore:
    """DeviceStore kept in dicts; mirrors the contract in docs/contracts/core.md."""

    def __init__(self) -> None:
        self.lookups = 0
        self._pairing: dict[str, datetime] = {}
        self._devices: dict[str, Device] = {}
        self._refresh: dict[str, tuple[str, bool]] = {}
        self._access: dict[str, tuple[str, datetime]] = {}

    def pairing_hashes(self) -> set[str]:
        return set(self._pairing)

    def all_hashes(self) -> set[str]:
        return set(self._pairing) | set(self._refresh) | set(self._access)

    def put_pairing(
        self,
        token_hash: str,
        expires_at: datetime,
        now: datetime,  # noqa: ARG002  (clear() drops expired ones too)
    ) -> None:
        self._pairing.clear()
        self._pairing[token_hash] = expires_at

    def take_pairing(self, token_hash: str, now: datetime) -> bool:
        self.lookups += 1
        expires_at = self._pairing.pop(token_hash, None)
        return expires_at is not None and expires_at > now

    def add_device(
        self, device: Device, refresh_hash: str, access_hash: str, access_expires_at: datetime
    ) -> None:
        if device.id in self._devices:
            msg = "device id already exists"
            raise ValueError(msg)
        self._devices[device.id] = device
        self._refresh[refresh_hash] = (device.id, False)
        self._access[access_hash] = (device.id, access_expires_at)

    def rotate_refresh(
        self,
        old_refresh_hash: str,
        new_refresh_hash: str,
        new_access_hash: str,
        access_expires_at: datetime,
        now: datetime,
    ) -> str | None:
        self.lookups += 1
        entry = self._refresh.get(old_refresh_hash)
        if entry is None or entry[1]:
            return None
        device_id = entry[0]
        self._refresh[old_refresh_hash] = (device_id, True)
        self._refresh[new_refresh_hash] = (device_id, False)
        self._access = {h: v for h, v in self._access.items() if v[0] != device_id}
        self._access[new_access_hash] = (device_id, access_expires_at)
        self._devices[device_id] = self._devices[device_id].model_copy(update={"last_seen_at": now})
        return device_id

    def refresh_record(self, refresh_hash: str) -> RefreshRecord | None:
        self.lookups += 1
        entry = self._refresh.get(refresh_hash)
        if entry is None:
            return None
        return RefreshRecord(device_id=entry[0], superseded=entry[1])

    def device_for_access(self, access_hash: str, now: datetime) -> str | None:
        self.lookups += 1
        entry = self._access.get(access_hash)
        if entry is None or entry[1] <= now:
            return None
        return entry[0]

    def list_devices(self) -> list[Device]:
        return sorted(self._devices.values(), key=lambda d: d.created_at)

    def remove_device(self, device_id: str) -> bool:
        if device_id not in self._devices:
            return False
        del self._devices[device_id]
        self._refresh = {h: v for h, v in self._refresh.items() if v[0] != device_id}
        self._access = {h: v for h, v in self._access.items() if v[0] != device_id}
        return True
