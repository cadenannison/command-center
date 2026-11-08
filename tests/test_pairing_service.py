"""PairingService: one-time pairing, rotating refresh credentials, reuse revokes the device."""

import logging
from datetime import timedelta

import pytest

from builders import NOW
from command_center.core.pairing import (
    ACCESS_TTL,
    FAILURE_LIMIT,
    LOCK_DURATION,
    PAIRING_TOKEN_BYTES,
    PAIRING_TTL,
    hash_token,
)
from command_center.services.errors import CredentialRejectedError, PairingLockedError
from command_center.services.pairing import PairingService
from fakes import FakeClock
from pairing_support import FakeTokenSource, InMemoryDeviceStore


class Rig:
    def __init__(self) -> None:
        self.clock = FakeClock(NOW)
        self.store = InMemoryDeviceStore()
        self.tokens = FakeTokenSource()
        self.service = PairingService(self.store, self.tokens, self.clock)

    def paired(self, name: str | None = "Pixel") -> "PairedPhone":
        offer = self.service.start_pairing()
        issued = self.service.pair(offer.token, name)
        return PairedPhone(issued.device_id, issued.access_token, issued.refresh_token)


class PairedPhone:
    def __init__(self, device_id: str, access: str, refresh: str) -> None:
        self.device_id = device_id
        self.access = access
        self.refresh = refresh


@pytest.fixture
def rig() -> Rig:
    return Rig()


def test_a_pairing_offer_is_128_bits_and_lives_five_minutes(rig: Rig) -> None:
    offer = rig.service.start_pairing()
    assert rig.tokens.requested[0] == PAIRING_TOKEN_BYTES == 16
    assert offer.expires_at == NOW + PAIRING_TTL == NOW + timedelta(minutes=5)


def test_a_pairing_token_is_stored_only_as_its_hash(rig: Rig) -> None:
    offer = rig.service.start_pairing()
    assert rig.store.pairing_hashes() == {hash_token(offer.token)}


def test_pairing_exchanges_the_token_for_credentials(rig: Rig) -> None:
    offer = rig.service.start_pairing()
    issued = rig.service.pair(offer.token, "Pixel 9")
    assert issued.access_expires_at == NOW + ACCESS_TTL == NOW + timedelta(minutes=15)
    assert issued.refresh_token != issued.access_token
    assert [d.name for d in rig.service.devices()] == ["Pixel 9"]


def test_credentials_are_stored_only_as_hashes(rig: Rig) -> None:
    phone = rig.paired()
    stored = rig.store.all_hashes()
    assert hash_token(phone.access) in stored
    assert hash_token(phone.refresh) in stored
    assert phone.access not in stored
    assert phone.refresh not in stored


def test_a_pairing_token_works_once(rig: Rig) -> None:
    offer = rig.service.start_pairing()
    rig.service.pair(offer.token, None)
    with pytest.raises(CredentialRejectedError):
        rig.service.pair(offer.token, None)


def test_a_pairing_token_expires_after_five_minutes(rig: Rig) -> None:
    offer = rig.service.start_pairing()
    rig.clock.advance(PAIRING_TTL)
    with pytest.raises(CredentialRejectedError):
        rig.service.pair(offer.token, None)


def test_a_new_offer_cancels_the_previous_one(rig: Rig) -> None:
    first = rig.service.start_pairing()
    rig.service.start_pairing()
    with pytest.raises(CredentialRejectedError):
        rig.service.pair(first.token, None)


def test_an_unplausible_token_is_rejected_without_a_lookup(rig: Rig) -> None:
    with pytest.raises(CredentialRejectedError):
        rig.service.pair("x" * 100_000, None)
    assert rig.store.lookups == 0


def test_the_device_name_is_cleaned(rig: Rig) -> None:
    offer = rig.service.start_pairing()
    rig.service.pair(offer.token, "  Pixel\n\t9 " + "z" * 200)
    (device,) = rig.service.devices()
    assert "\n" not in device.name
    assert len(device.name) <= 64


def test_five_wrong_tokens_lock_pairing_for_sixty_seconds(rig: Rig) -> None:
    offer = rig.service.start_pairing()
    for _ in range(FAILURE_LIMIT):
        with pytest.raises(CredentialRejectedError):
            rig.service.pair("fake-wrong-token-0000000000", None)
    with pytest.raises(PairingLockedError) as locked:
        rig.service.pair(offer.token, None)  # even the right token waits out the lock
    assert locked.value.retry_after_seconds == int(LOCK_DURATION.total_seconds())


def test_pairing_works_again_after_the_lock_expires(rig: Rig) -> None:
    offer = rig.service.start_pairing()
    for _ in range(FAILURE_LIMIT):
        with pytest.raises(CredentialRejectedError):
            rig.service.pair("fake-wrong-token-0000000000", None)
    rig.clock.advance(LOCK_DURATION)
    assert rig.service.pair(offer.token, None).device_id


def test_the_lock_message_reports_the_time_left(rig: Rig) -> None:
    for _ in range(FAILURE_LIMIT):
        with pytest.raises(CredentialRejectedError):
            rig.service.pair("fake-wrong-token-0000000000", None)
    rig.clock.advance(timedelta(seconds=45))
    with pytest.raises(PairingLockedError) as locked:
        rig.service.pair("fake-wrong-token-0000000000", None)
    assert locked.value.retry_after_seconds == 15


def test_an_access_token_identifies_its_device(rig: Rig) -> None:
    phone = rig.paired()
    assert rig.service.authenticate(phone.access) == phone.device_id


def test_an_access_token_stops_working_after_fifteen_minutes(rig: Rig) -> None:
    phone = rig.paired()
    rig.clock.advance(ACCESS_TTL)
    assert rig.service.authenticate(phone.access) is None


def test_a_refresh_credential_is_not_an_access_token(rig: Rig) -> None:
    phone = rig.paired()
    assert rig.service.authenticate(phone.refresh) is None


def test_an_unknown_or_empty_access_token_identifies_nobody(rig: Rig) -> None:
    rig.paired()
    assert rig.service.authenticate("fake-unknown-access-token") is None
    assert rig.service.authenticate("") is None


def test_refresh_rotates_the_credential_and_issues_a_new_access_token(rig: Rig) -> None:
    phone = rig.paired()
    rig.clock.advance(timedelta(minutes=14))
    issued = rig.service.refresh(phone.refresh)
    assert issued.device_id == phone.device_id
    assert issued.refresh_token != phone.refresh
    assert issued.access_token != phone.access
    assert issued.access_expires_at == rig.clock.now() + ACCESS_TTL
    assert rig.service.authenticate(issued.access_token) == phone.device_id


def test_refresh_ends_the_old_access_token(rig: Rig) -> None:
    phone = rig.paired()
    rig.service.refresh(phone.refresh)
    assert rig.service.authenticate(phone.access) is None


def test_reusing_a_rotated_refresh_credential_revokes_the_device(rig: Rig) -> None:
    phone = rig.paired()
    newer = rig.service.refresh(phone.refresh)
    with pytest.raises(CredentialRejectedError):
        rig.service.refresh(phone.refresh)
    assert rig.service.devices() == []
    assert rig.service.authenticate(newer.access_token) is None
    with pytest.raises(CredentialRejectedError):
        rig.service.refresh(newer.refresh_token)


def test_reuse_of_a_credential_two_rotations_old_still_revokes(rig: Rig) -> None:
    phone = rig.paired()
    first = rig.service.refresh(phone.refresh)
    rig.service.refresh(first.refresh_token)
    with pytest.raises(CredentialRejectedError):
        rig.service.refresh(phone.refresh)
    assert rig.service.devices() == []


def test_an_unknown_refresh_credential_is_rejected_and_revokes_nobody(rig: Rig) -> None:
    rig.paired()
    with pytest.raises(CredentialRejectedError):
        rig.service.refresh("fake-unknown-refresh-credential")
    assert len(rig.service.devices()) == 1


def test_refresh_failures_lock_refreshing_after_five(rig: Rig) -> None:
    phone = rig.paired()
    for _ in range(FAILURE_LIMIT):
        with pytest.raises(CredentialRejectedError):
            rig.service.refresh("fake-unknown-refresh-credential")
    with pytest.raises(PairingLockedError):
        rig.service.refresh(phone.refresh)


def test_pairing_failures_do_not_lock_refreshing(rig: Rig) -> None:
    phone = rig.paired()
    for _ in range(FAILURE_LIMIT):
        with pytest.raises(CredentialRejectedError):
            rig.service.pair("fake-wrong-token-0000000000", None)
    assert rig.service.refresh(phone.refresh).device_id == phone.device_id


def test_revoking_a_device_ends_its_access_and_refresh(rig: Rig) -> None:
    phone = rig.paired()
    assert rig.service.revoke(phone.device_id) is True
    assert rig.service.authenticate(phone.access) is None
    with pytest.raises(CredentialRejectedError):
        rig.service.refresh(phone.refresh)


def test_revoking_an_unknown_device_reports_false(rig: Rig) -> None:
    assert rig.service.revoke("fake-no-such-device") is False


def test_one_phone_revoked_leaves_the_others(rig: Rig) -> None:
    first = rig.paired("One")
    second = rig.paired("Two")
    rig.service.revoke(first.device_id)
    assert rig.service.authenticate(second.access) == second.device_id


def test_logs_never_carry_a_token_or_credential(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    offer = rig.service.start_pairing()
    phone = rig.service.pair(offer.token, "Pixel")
    newer = rig.service.refresh(phone.refresh_token)
    with pytest.raises(CredentialRejectedError):
        rig.service.refresh(phone.refresh_token)  # reuse, which logs a warning
    with pytest.raises(CredentialRejectedError):
        rig.service.pair("fake-wrong-token-0000000000", None)
    text = caplog.text + repr(caplog.records[0].__dict__)
    for secret in (
        offer.token,
        phone.access_token,
        phone.refresh_token,
        newer.access_token,
        newer.refresh_token,
        "fake-wrong-token-0000000000",
    ):
        assert secret not in caplog.text
        assert secret not in text
    assert any("reuse" in record.getMessage() for record in caplog.records)


def test_issued_tokens_do_not_print_their_secrets(rig: Rig) -> None:
    phone = rig.service.pair(rig.service.start_pairing().token, None)
    assert phone.access_token not in repr(phone)
    assert phone.refresh_token not in repr(phone)
