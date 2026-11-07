"""SettingsService: validate-then-store, key-by-key merging, write-only status, error states."""

import asyncio
from collections.abc import Mapping

import pytest

from builders import NOW
from command_center.core.errors import AuthExpired, FatalError, SecretStoreError, TransientError
from command_center.core.ports import SecretStore
from command_center.core.schema import SecretStatus, ValidationResult
from command_center.services.errors import UnknownSourceError
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from fake_adapter import (
    KEYCHAIN_DETAIL,
    FailingSecondSetSecretStore,
    FakeAdapter,
    RecordingSleep,
    UnavailableSecretStore,
)
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

CRED = "fake-canvas-token-1234"
BASE = "fake-canvas-base-url"


class FlakyReads(InMemorySecretStore):
    """An in-memory SecretStore whose status call can be switched to fail."""

    broken = False

    def status(self, source: str, *, user_id: str = "local") -> Mapping[str, SecretStatus]:
        if self.broken:
            raise SecretStoreError(KEYCHAIN_DETAIL)
        return super().status(source, user_id=user_id)


def make_services(
    adapter: FakeAdapter | None = None,
    secrets: SecretStore | None = None,
) -> tuple[SettingsService, SyncService, FakeAdapter, SecretStore]:
    adapter = adapter or FakeAdapter()
    store: SecretStore = secrets if secrets is not None else InMemorySecretStore()
    adapters = {adapter.name: adapter}
    sync = SyncService(
        adapters, store, InMemoryEventStore(), FakeClock(NOW), sleep=RecordingSleep()
    )
    return SettingsService(adapters, store, sync), sync, adapter, store


async def test_connect_validates_and_stores_every_field_without_running_the_sync() -> None:
    settings, _, adapter, secrets = make_services()

    result = await settings.connect("canvas", {"token": CRED, "base_url": BASE})

    assert adapter.validations == [{"token": CRED, "base_url": BASE}]
    assert dict(secrets.get("canvas")) == {"token": CRED, "base_url": BASE}
    assert adapter.fetches == []
    assert (result.ok, result.message) == (True, "Connected")
    assert result.sync is not None
    assert result.sync.status == "syncing"


async def test_connect_returns_while_the_adapter_is_still_fetching() -> None:
    gate = asyncio.Event()  # never opened: a connect that waited for the sync would hang
    settings, sync, adapter, _ = make_services(FakeAdapter(gate=gate))

    result = await asyncio.wait_for(settings.connect("canvas", {"token": CRED}), timeout=1)

    assert result.ok
    state = sync.state("canvas")
    assert state is not None
    assert state.status == "syncing"
    assert adapter.fetches == []


async def test_status_shows_syncing_while_the_sync_runs_and_the_result_after() -> None:
    gate = asyncio.Event()
    settings, sync, _, _ = make_services(FakeAdapter(gate=gate))
    await settings.connect("canvas", {"token": CRED})

    running = asyncio.create_task(sync.sync("canvas"))
    await asyncio.sleep(0)
    (during,) = await settings.status()
    gate.set()
    await running
    (after,) = await settings.status()

    assert during.sync is not None
    assert after.sync is not None
    assert (during.sync.status, after.sync.status) == ("syncing", "ok")


async def test_connect_merges_updated_creds_over_the_submitted_ones_key_by_key() -> None:
    refreshed = ValidationResult(
        ok=True, message="Connected", updated_creds={"token": "fake-new-1"}
    )
    settings, _, _, secrets = make_services(FakeAdapter(validation=refreshed))

    await settings.connect("canvas", {"token": CRED, "base_url": BASE})

    assert dict(secrets.get("canvas")) == {"token": "fake-new-1", "base_url": BASE}


async def test_connect_keeps_stored_keys_that_the_new_credentials_do_not_mention() -> None:
    settings, _, _, secrets = make_services()
    secrets.set("canvas", "base_url", BASE)

    await settings.connect("canvas", {"token": CRED})

    assert dict(secrets.get("canvas")) == {"token": CRED, "base_url": BASE}


async def test_rejected_credentials_are_not_stored_and_do_not_sync() -> None:
    rejected = ValidationResult(ok=False, message="Token rejected (401)")
    settings, sync, adapter, secrets = make_services(FakeAdapter(validation=rejected))

    result = await settings.connect("canvas", {"token": CRED})

    assert (result.ok, result.message, result.sync) == (False, "Token rejected (401)", None)
    assert secrets.get("canvas") == {}
    assert adapter.fetches == []
    assert sync.state("canvas") is None


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (AuthExpired("x"), "Credentials were rejected"),
        (TransientError("timeout"), "Could not validate credentials: timeout"),
        (FatalError("bad url"), "Could not validate credentials: bad url"),
    ],
)
async def test_validation_failures_are_results_not_exceptions(
    error: Exception, expected: str
) -> None:
    settings, _, _, secrets = make_services(FakeAdapter(validate_error=error))

    result = await settings.connect("canvas", {"token": CRED})

    assert (result.ok, result.message) == (False, expected)
    assert secrets.get("canvas") == {}


async def test_connect_with_an_unavailable_secret_store_is_an_error_state() -> None:
    settings, _, adapter, _ = make_services(secrets=UnavailableSecretStore())

    result = await settings.connect("canvas", {"token": CRED})

    assert (result.ok, result.message) == (False, "secret store unavailable")
    assert result.sync is not None
    assert (result.sync.status, result.sync.message) == ("error", "secret store unavailable")
    assert adapter.fetches == []


async def test_a_store_failure_part_way_through_leaves_the_earlier_keys_and_reports_it() -> None:
    store = FailingSecondSetSecretStore()
    settings, *_ = make_services(secrets=store)

    result = await settings.connect("canvas", {"token": CRED, "base_url": BASE})

    assert (result.ok, result.message) == (False, "secret store unavailable")
    assert dict(store.get("canvas")) == {"token": CRED}


async def test_connecting_an_unknown_source_is_rejected() -> None:
    settings, *_ = make_services()

    with pytest.raises(UnknownSourceError):
        await settings.connect("gmail", {"token": CRED})


async def test_status_reports_set_and_last4_per_key_plus_the_sync_state() -> None:
    settings, sync, _, _ = make_services()
    await settings.connect("canvas", {"token": CRED, "pin": "1234"})
    await sync.sync("canvas")

    (status,) = await settings.status()

    assert status.source == "canvas"
    assert (status.keys["token"].set, status.keys["token"].last4) == (True, "1234")
    assert (status.keys["pin"].set, status.keys["pin"].last4) == (True, None)
    assert status.sync is not None
    assert status.sync.status == "ok"


async def test_status_never_contains_a_secret_value() -> None:
    settings, _, _, _ = make_services()
    await settings.connect("canvas", {"token": CRED})

    (status,) = await settings.status()

    assert CRED not in status.model_dump_json()
    assert CRED not in repr(status)


async def test_status_of_a_source_never_connected_has_no_keys_and_no_sync() -> None:
    settings, *_ = make_services()

    (status,) = await settings.status()

    assert (status.keys, status.sync) == ({}, None)


async def test_status_with_an_unavailable_secret_store_is_an_error_state() -> None:
    settings, *_ = make_services(secrets=UnavailableSecretStore())

    (status,) = await settings.status()

    assert status.keys == {}
    assert status.sync is not None
    assert (status.sync.status, status.sync.message) == ("error", "secret store unavailable")


async def test_a_status_read_does_not_replace_the_remembered_sync_result() -> None:
    adapter = FakeAdapter()
    store = FlakyReads()
    settings, sync, *_ = make_services(adapter, secrets=store)
    await sync.sync("canvas")
    remembered = sync.state("canvas")
    store.broken = True

    (status,) = await settings.status()

    assert status.sync is not None
    assert status.sync.message == "secret store unavailable"
    assert sync.state("canvas") == remembered


async def test_disconnect_deletes_every_key_and_forgets_the_sync_state() -> None:
    settings, sync, _, secrets = make_services()
    await settings.connect("canvas", {"token": CRED, "base_url": BASE})

    result = await settings.disconnect("canvas")

    assert secrets.get("canvas") == {}
    assert (result.keys, result.sync) == ({}, None)
    assert sync.state("canvas") is None


async def test_disconnect_with_an_unavailable_secret_store_is_an_error_state() -> None:
    settings, *_ = make_services(secrets=UnavailableSecretStore())

    result = await settings.disconnect("canvas")

    assert result.sync is not None
    assert result.sync.message == "secret store unavailable"


async def test_disconnecting_an_unknown_source_is_rejected() -> None:
    settings, *_ = make_services()

    with pytest.raises(UnknownSourceError):
        await settings.disconnect("gmail")
