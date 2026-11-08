"""SettingsService.connect validates and stores the stored credentials plus the submitted ones."""

import pytest

from builders import NOW
from command_center.core.errors import SecretStoreError
from command_center.core.ports import SecretStore
from command_center.core.schema import ValidationResult
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from fake_adapter import KEYCHAIN_DETAIL, FakeAdapter, RecordingSleep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

TOKEN = "fake-canvas-token-1234"  # noqa: S105  (fake- test value)
OLD_URL = "fake-old-base-url"
NEW_URL = "fake-new-base-url"


class RecordingSecretStore(InMemorySecretStore):
    """An in-memory SecretStore that remembers every key written."""

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[tuple[str, str]] = []

    def set(self, source: str, key: str, value: str, *, user_id: str = "local") -> None:
        self.writes.append((key, value))
        super().set(source, key, value, user_id=user_id)


class UnreadableSecretStore(InMemorySecretStore):
    """A SecretStore whose reads fail like a locked keychain, while writes would work."""

    def get(self, source: str, *, user_id: str = "local") -> dict[str, str]:  # noqa: ARG002
        raise SecretStoreError(KEYCHAIN_DETAIL)


def make_settings(
    store: SecretStore, adapter: FakeAdapter | None = None
) -> tuple[SettingsService, FakeAdapter]:
    adapter = adapter or FakeAdapter()
    adapters = {adapter.name: adapter}
    sync = SyncService(
        adapters, store, InMemoryEventStore(), FakeClock(NOW), sleep=RecordingSleep()
    )
    return SettingsService(adapters, store, sync), adapter


def connected_store() -> RecordingSecretStore:
    store = RecordingSecretStore()
    store.set("canvas", "token", TOKEN)
    store.set("canvas", "base_url", OLD_URL)
    store.writes.clear()
    return store


async def test_changing_only_base_url_keeps_the_stored_token_and_validates_the_merged_set() -> None:
    store = connected_store()
    settings, adapter = make_settings(store)

    result = await settings.connect("canvas", {"base_url": NEW_URL})

    assert result.ok
    assert adapter.validations == [{"token": TOKEN, "base_url": NEW_URL}]
    assert dict(store.get("canvas")) == {"token": TOKEN, "base_url": NEW_URL}


@pytest.mark.parametrize("blank", ["", " ", "  \t\n"])
async def test_a_blank_or_whitespace_field_keeps_the_stored_value(blank: str) -> None:
    store = connected_store()
    settings, adapter = make_settings(store)

    await settings.connect("canvas", {"token": blank, "base_url": NEW_URL})

    assert adapter.validations == [{"token": TOKEN, "base_url": NEW_URL}]
    assert dict(store.get("canvas")) == {"token": TOKEN, "base_url": NEW_URL}


async def test_an_all_blank_submit_validates_the_stored_set_unchanged() -> None:
    store = connected_store()
    settings, adapter = make_settings(store)

    result = await settings.connect("canvas", {"token": "", "base_url": " "})

    assert result.ok
    assert adapter.validations == [{"token": TOKEN, "base_url": OLD_URL}]
    assert dict(store.get("canvas")) == {"token": TOKEN, "base_url": OLD_URL}


async def test_a_blank_field_with_nothing_stored_is_not_passed_to_the_adapter() -> None:
    store = RecordingSecretStore()
    settings, adapter = make_settings(store)

    await settings.connect("canvas", {"token": TOKEN, "base_url": "  "})

    assert adapter.validations == [{"token": TOKEN}]
    assert dict(store.get("canvas")) == {"token": TOKEN}


async def test_updated_creds_from_the_adapter_win_over_the_merged_set() -> None:
    refreshed = ValidationResult(
        ok=True, message="Connected", updated_creds={"token": "fake-new-1"}
    )
    store = connected_store()
    settings, _ = make_settings(store, FakeAdapter(validation=refreshed))

    await settings.connect("canvas", {"base_url": NEW_URL})

    assert dict(store.get("canvas")) == {"token": "fake-new-1", "base_url": NEW_URL}


async def test_only_the_keys_that_changed_are_written() -> None:
    store = connected_store()
    settings, _ = make_settings(store)

    await settings.connect("canvas", {"token": TOKEN, "base_url": NEW_URL})

    assert store.writes == [("base_url", NEW_URL)]


async def test_rejected_merged_credentials_leave_the_stored_ones_alone() -> None:
    rejected = ValidationResult(ok=False, message="Token rejected (401)")
    store = connected_store()
    settings, _ = make_settings(store, FakeAdapter(validation=rejected))

    result = await settings.connect("canvas", {"base_url": NEW_URL})

    assert (result.ok, result.sync) == (False, None)
    assert dict(store.get("canvas")) == {"token": TOKEN, "base_url": OLD_URL}
    assert store.writes == []


async def test_an_unreadable_secret_store_is_reported_without_validating_or_storing() -> None:
    store = UnreadableSecretStore()
    settings, adapter = make_settings(store)

    result = await settings.connect("canvas", {"token": TOKEN})

    assert (result.ok, result.message) == (False, "secret store unavailable")
    assert result.sync is not None
    assert (result.sync.status, result.sync.message) == ("error", "secret store unavailable")
    assert adapter.validations == []
    assert KEYCHAIN_DETAIL not in result.model_dump_json()
