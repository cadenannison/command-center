"""SettingsService: plain values, failed connects keep storage, unverified, test, checklist."""

from datetime import timedelta

import pytest

from builders import NOW
from command_center.core.errors import AuthExpired, FatalError, TransientError
from command_center.core.schema import ValidationResult
from command_center.services.credential_fields import is_secret
from command_center.services.errors import UnknownSourceError
from command_center.services.settings import (
    NOT_CONNECTED_MESSAGE,
    UNVERIFIED_PREFIX,
    SettingsService,
)
from command_center.services.sync import SyncService
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

TOKEN = "fake-canvas-token-ABCD1234"  # noqa: S105  (fake- test value)
URL = "https://fake-school.example"
NEW_URL = "https://fake-other.example"


def make(
    adapter: FakeAdapter | None = None, *, with_clock: bool = True
) -> tuple[SettingsService, SyncService, FakeAdapter, InMemorySecretStore, FakeClock]:
    adapter = adapter or FakeAdapter()
    secrets = InMemorySecretStore()
    clock = FakeClock(NOW)
    adapters = {adapter.name: adapter}
    sync = SyncService(adapters, secrets, InMemoryEventStore(), clock, sleep=RecordingSleep())
    settings = SettingsService(adapters, secrets, sync, clock=clock if with_clock else None)
    return settings, sync, adapter, secrets, clock


def store_good_credentials(secrets: InMemorySecretStore) -> None:
    secrets.set("canvas", "token", TOKEN)
    secrets.set("canvas", "base_url", URL)


@pytest.mark.parametrize(
    ("source", "key", "secret"),
    [
        ("canvas", "base_url", False),
        ("canvas", "token", True),
        ("apple_calendar", "username", False),
        ("apple_calendar", "app_password", True),
        ("weather", "latitude", False),
        ("weather", "longitude", False),
        ("learningsuite", "urls", True),
        ("gmail", "client_json", True),
        ("gemini", "api_key", True),
        ("gmail", "token", True),
        ("a-new-source", "anything", True),
    ],
)
def test_a_key_is_secret_unless_it_is_listed_as_plain(
    source: str,
    key: str,
    secret: bool,  # noqa: FBT001
) -> None:
    assert is_secret(source, key) is secret


async def test_status_shows_the_value_of_a_plain_key_and_only_set_and_last4_of_a_secret() -> None:
    settings, _, _, secrets, _ = make()
    store_good_credentials(secrets)

    (item,) = await settings.status()

    assert item.values == {"base_url": URL}
    assert item.keys["token"].set
    assert item.keys["token"].last4 == "1234"
    assert TOKEN not in item.model_dump_json()


async def test_status_has_no_values_before_anything_is_stored() -> None:
    settings, *_ = make()

    (item,) = await settings.status()

    assert item.values == {}


@pytest.mark.parametrize(
    "error", [AuthExpired("no"), TransientError("offline"), FatalError("bad url")]
)
async def test_stored_good_credentials_survive_a_failed_connect(error: Exception) -> None:
    settings, _, _, secrets, _ = make(FakeAdapter(validate_error=error))
    store_good_credentials(secrets)

    result = await settings.connect(
        "canvas", {"token": "fake-bad-token-99999999", "base_url": NEW_URL}
    )

    assert not result.ok
    assert dict(secrets.get("canvas")) == {"token": TOKEN, "base_url": URL}


async def test_stored_good_credentials_survive_a_rejected_validation_result() -> None:
    rejected = ValidationResult(ok=False, message="Token rejected (401)")
    settings, _, _, secrets, _ = make(FakeAdapter(validation=rejected))
    store_good_credentials(secrets)

    await settings.connect("canvas", {"token": "fake-bad-token-99999999"})

    assert dict(secrets.get("canvas")) == {"token": TOKEN, "base_url": URL}


async def test_only_a_transient_failure_offers_to_save_unverified() -> None:
    offered = {}
    for name, error in {
        "transient": TransientError("offline"),
        "auth": AuthExpired("no"),
        "fatal": FatalError("bad url"),
    }.items():
        settings, *_ = make(FakeAdapter(validate_error=error))
        offered[name] = (await settings.connect("canvas", {"token": TOKEN})).can_save_unverified

    assert offered == {"transient": True, "auth": False, "fatal": False}


async def test_a_rejected_validation_result_does_not_offer_unverified() -> None:
    rejected = ValidationResult(ok=False, message="Token rejected (401)")
    settings, *_ = make(FakeAdapter(validation=rejected))

    result = await settings.connect("canvas", {"token": TOKEN})

    assert not result.can_save_unverified


async def test_a_successful_connect_does_not_offer_unverified() -> None:
    settings, *_ = make()

    assert not (await settings.connect("canvas", {"token": TOKEN})).can_save_unverified


async def test_save_unverified_stores_the_typed_values_without_validating_or_syncing() -> None:
    settings, sync, adapter, secrets, _ = make()
    secrets.set("canvas", "base_url", URL)

    result = await settings.save_unverified("canvas", {"token": TOKEN})

    assert dict(secrets.get("canvas")) == {"token": TOKEN, "base_url": URL}
    assert (adapter.validations, adapter.fetches) == ([], [])
    assert result.ok
    assert sync.state("canvas") is not None


async def test_save_unverified_with_nothing_typed_stores_nothing_and_leaves_the_state() -> None:
    settings, sync, _, secrets, _ = make()
    secrets.set("canvas", "token", TOKEN)

    result = await settings.save_unverified("canvas", {"token": "   "})

    assert (result.ok, result.message) == (False, "Nothing was entered, so nothing was saved")
    assert dict(secrets.get("canvas")) == {"token": TOKEN}
    assert sync.state("canvas") is None


async def test_save_unverified_leaves_an_error_state_that_says_unverified() -> None:
    settings, sync, _, _, _ = make()

    result = await settings.save_unverified("canvas", {"token": TOKEN})

    state = sync.state("canvas")
    assert state is not None
    assert (state.status, result.sync) == ("error", state)
    assert state.message.startswith(UNVERIFIED_PREFIX)
    assert result.message.startswith(UNVERIFIED_PREFIX)


async def test_save_unverified_keeps_a_stored_value_for_a_blank_field() -> None:
    settings, _, _, secrets, _ = make()
    store_good_credentials(secrets)

    await settings.save_unverified("canvas", {"token": "  ", "base_url": NEW_URL})

    assert dict(secrets.get("canvas")) == {"token": TOKEN, "base_url": NEW_URL}


async def test_save_unverified_of_an_unknown_source_raises() -> None:
    settings, *_ = make()

    with pytest.raises(UnknownSourceError):
        await settings.save_unverified("nope", {"token": TOKEN})


async def test_check_connection_validates_the_stored_credentials_and_changes_nothing() -> None:
    settings, sync, adapter, secrets, _ = make()
    store_good_credentials(secrets)

    result = await settings.check_connection("canvas")

    assert (result.ok, result.sync) == (True, None)
    assert adapter.validations == [{"token": TOKEN, "base_url": URL}]
    assert (adapter.fetches, sync.state("canvas")) == ([], None)


async def test_check_connection_says_so_when_nothing_is_stored() -> None:
    settings, _, adapter, _, _ = make()

    result = await settings.check_connection("canvas")

    assert (result.ok, result.message) == (False, NOT_CONNECTED_MESSAGE)
    assert adapter.validations == []


async def test_check_connection_stores_a_refreshed_credential() -> None:
    refreshed = ValidationResult(
        ok=True, message="Connected", updated_creds={"token": "fake-new-1"}
    )
    settings, _, _, secrets, _ = make(FakeAdapter(validation=refreshed))
    store_good_credentials(secrets)

    await settings.check_connection("canvas")

    assert dict(secrets.get("canvas")) == {"token": "fake-new-1", "base_url": URL}


async def test_check_connection_redacts_the_failure_message() -> None:
    settings, _, _, secrets, _ = make(
        FakeAdapter(validate_error=TransientError("could not reach me@example.test 123456789"))
    )
    store_good_credentials(secrets)

    result = await settings.check_connection("canvas")

    assert not result.ok
    assert "me@example.test" not in result.message
    assert "123456789" not in result.message
    assert not result.can_save_unverified or "[email]" in result.message


async def test_the_checklist_marks_a_never_connected_source_not_connected() -> None:
    settings, *_ = make()

    (row,) = settings.checklist(await settings.status())

    assert (row.state, row.last_sync_at, row.seconds_ago) == ("not_connected", None, None)


async def test_the_checklist_marks_a_synced_source_connected_with_its_age() -> None:
    settings, sync, _, secrets, clock = make()
    store_good_credentials(secrets)
    await sync.sync("canvas")
    clock.advance(timedelta(minutes=3))

    (row,) = settings.checklist(await settings.status())

    assert (row.state, row.sync_status, row.seconds_ago) == ("connected", "ok", 180)


@pytest.mark.parametrize("error", [AuthExpired("no"), FatalError("boom")])
async def test_the_checklist_marks_a_failed_source_needs_attention(error: Exception) -> None:
    settings, sync, _, secrets, _ = make(FakeAdapter(script=[error]))
    store_good_credentials(secrets)
    await sync.sync("canvas")

    (row,) = settings.checklist(await settings.status())

    assert row.state == "needs_attention"


async def test_the_checklist_marks_an_unverified_save_needs_attention() -> None:
    settings, *_ = make()
    await settings.save_unverified("canvas", {"token": TOKEN})

    (row,) = settings.checklist(await settings.status())

    assert (row.state, row.message.startswith(UNVERIFIED_PREFIX)) == ("needs_attention", True)


async def test_the_checklist_marks_stored_keys_without_a_sync_connected() -> None:
    settings, _, _, secrets, _ = make()
    store_good_credentials(secrets)

    (row,) = settings.checklist(await settings.status())

    assert (row.state, row.seconds_ago) == ("connected", None)


async def test_the_checklist_has_no_age_without_a_clock() -> None:
    settings, sync, _, secrets, _ = make(with_clock=False)
    store_good_credentials(secrets)
    await sync.sync("canvas")

    (row,) = settings.checklist(await settings.status())

    assert (row.last_sync_at, row.seconds_ago) == (NOW, None)
