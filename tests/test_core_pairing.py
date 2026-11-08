"""Pairing core: token hashing, plausibility, device names, models and the failure limiter."""

# ruff: noqa: S105, S106  (invented "fake-" tokens in tests, not real credentials)

import unicodedata
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from command_center.core.pairing import (
    ACCESS_TTL,
    CREDENTIAL_TOKEN_BYTES,
    DEFAULT_DEVICE_NAME,
    DEVICE_ID_BYTES,
    FAILURE_LIMIT,
    LOCK_DURATION,
    MAX_DEVICE_NAME,
    PAIRING_TOKEN_BYTES,
    PAIRING_TTL,
    Device,
    FailureLimiter,
    IssuedTokens,
    PairingOffer,
    RefreshRecord,
    clean_device_name,
    hash_token,
    hashes_match,
    is_plausible_token,
)
from fakes import FakeClock

START = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
NAIVE = datetime(2026, 11, 7, 12, 0)  # noqa: DTZ001


def test_constants_have_the_agreed_values() -> None:
    assert PAIRING_TOKEN_BYTES == 16
    assert CREDENTIAL_TOKEN_BYTES == 32
    assert DEVICE_ID_BYTES == 16
    assert timedelta(minutes=5) == PAIRING_TTL
    assert timedelta(minutes=15) == ACCESS_TTL
    assert MAX_DEVICE_NAME == 64
    assert FAILURE_LIMIT == 5
    assert timedelta(seconds=60) == LOCK_DURATION
    assert DEFAULT_DEVICE_NAME == "Phone"


# ---------------------------------------------------------------- hash_token / hashes_match


def test_hash_token_is_sha256_hex_of_the_utf8_token() -> None:
    assert hash_token("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


@given(st.text(), st.text())
def test_hash_token_is_deterministic_hex_and_collision_free_on_distinct_inputs(
    a: str, b: str
) -> None:
    digest = hash_token(a)
    assert digest == hash_token(a)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
    if a != b:
        assert digest != hash_token(b)


def test_hashes_match_is_true_for_equal_and_false_for_different_values() -> None:
    digest = hash_token("fake-token-value-0001")
    assert hashes_match(digest, hash_token("fake-token-value-0001"))
    assert not hashes_match(digest, hash_token("fake-token-value-0002"))


@given(st.text(), st.text())
def test_hashes_match_never_raises_and_agrees_with_equality(a: str, b: str) -> None:
    assert hashes_match(a, b) == (a == b)


# ---------------------------------------------------------------- is_plausible_token


@pytest.mark.parametrize(
    "token",
    ["a" * 16, "A" * 128, "fake-token_0123456789", "fake-0123456789abcdef"],
)
def test_plausible_token_accepts_url_safe_tokens_of_16_to_128_characters(token: str) -> None:
    assert is_plausible_token(token)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "a" * 15,
        "a" * 129,
        "a" * 15 + " ",
        "a" * 16 + "\n",
        "a" * 15 + "+",
        "a" * 15 + "/",
        "a" * 15 + "=",
        "a" * 15 + "\u00e9",
        "a" * 15 + "\u0661",
        "a" * 15 + "\x00",
    ],
)
def test_plausible_token_rejects_wrong_length_or_alphabet(token: str) -> None:
    assert not is_plausible_token(token)


@given(st.text())
def test_plausible_token_never_raises(token: str) -> None:
    assert isinstance(is_plausible_token(token), bool)


# ---------------------------------------------------------------- clean_device_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "Phone"),
        ("", "Phone"),
        ("   ", "Phone"),
        ("\x00\x07", "Phone"),
        ("\u200b\u202e", "Phone"),
        ("  Caden's iPhone  ", "Caden's iPhone"),
        ("My   \t Phone\nTwo", "My Phone Two"),
        ("Pi\x00xel\u200b 9", "Pixel 9"),
    ],
)
def test_clean_device_name_examples(raw: str | None, expected: str) -> None:
    assert clean_device_name(raw) == expected


def test_clean_device_name_truncates_to_the_maximum() -> None:
    assert clean_device_name("x" * 200) == "x" * MAX_DEVICE_NAME


def test_clean_device_name_does_not_leave_a_trailing_space_after_truncation() -> None:
    raw = "x" * (MAX_DEVICE_NAME - 1) + " tail"
    assert clean_device_name(raw) == "x" * (MAX_DEVICE_NAME - 1)


@given(st.one_of(st.none(), st.text()))
def test_clean_device_name_is_always_1_to_64_characters_without_control_characters(
    raw: str | None,
) -> None:
    name = clean_device_name(raw)
    assert 1 <= len(name) <= MAX_DEVICE_NAME
    assert all(unicodedata.category(c) not in {"Cc", "Cf"} for c in name)
    assert name == name.strip()
    assert "  " not in name


@given(st.text())
def test_clean_device_name_is_idempotent(raw: str) -> None:
    once = clean_device_name(raw)
    assert clean_device_name(once) == once


# ---------------------------------------------------------------- models


def test_device_requires_timezone_aware_datetimes() -> None:
    with pytest.raises(ValidationError):
        Device(id="dev-1", name="Phone", created_at=NAIVE, last_seen_at=START)
    with pytest.raises(ValidationError):
        Device(id="dev-1", name="Phone", created_at=START, last_seen_at=NAIVE)


def test_models_are_frozen_and_forbid_extra_fields() -> None:
    device = Device(id="dev-1", name="Phone", created_at=START, last_seen_at=START)
    with pytest.raises(ValidationError):
        device.name = "Other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Device(id="dev-1", name="Phone", created_at=START, last_seen_at=START, extra=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        RefreshRecord(device_id="dev-1", superseded=False, extra=1)  # type: ignore[call-arg]


def test_pairing_offer_and_issued_tokens_reject_naive_datetimes() -> None:
    with pytest.raises(ValidationError):
        PairingOffer(token="fake-pairing-token-1", expires_at=NAIVE)
    with pytest.raises(ValidationError):
        IssuedTokens(
            device_id="dev-1",
            access_token="fake-access-token-1",
            access_expires_at=NAIVE,
            refresh_token="fake-refresh-token-1",
        )


def test_pairing_offer_repr_and_str_hide_the_token() -> None:
    offer = PairingOffer(token="fake-secret-pairing-token", expires_at=START)
    assert "fake-secret-pairing-token" not in repr(offer)
    assert "fake-secret-pairing-token" not in str(offer)
    assert offer.token == "fake-secret-pairing-token"


def test_issued_tokens_repr_and_str_hide_both_tokens() -> None:
    issued = IssuedTokens(
        device_id="dev-1",
        access_token="fake-secret-access-token",
        access_expires_at=START,
        refresh_token="fake-secret-refresh-token",
    )
    for text in (repr(issued), str(issued), f"{issued}", f"{issued!r}"):
        assert "fake-secret-access-token" not in text
        assert "fake-secret-refresh-token" not in text
        assert "dev-1" in text


def test_refresh_record_holds_device_id_and_superseded_flag() -> None:
    record = RefreshRecord(device_id="dev-1", superseded=True)
    assert record.device_id == "dev-1"
    assert record.superseded is True


# ---------------------------------------------------------------- FailureLimiter


def test_limiter_defaults_match_the_constants() -> None:
    clock = FakeClock(START)
    limiter = FailureLimiter()
    for _ in range(FAILURE_LIMIT):
        limiter.record_failure(clock.now())
    assert limiter.locked_for(clock.now()) == LOCK_DURATION


def test_limiter_is_not_locked_when_new() -> None:
    assert FailureLimiter().locked_for(START) is None


def test_limiter_locks_on_the_fifth_failure_not_before() -> None:
    clock = FakeClock(START)
    limiter = FailureLimiter()
    for _ in range(4):
        limiter.record_failure(clock.now())
        assert limiter.locked_for(clock.now()) is None
    limiter.record_failure(clock.now())
    assert limiter.locked_for(clock.now()) == timedelta(seconds=60)


def test_limiter_success_after_four_failures_resets_the_count() -> None:
    clock = FakeClock(START)
    limiter = FailureLimiter()
    for _ in range(4):
        limiter.record_failure(clock.now())
    limiter.record_success()
    for _ in range(4):
        limiter.record_failure(clock.now())
    assert limiter.locked_for(clock.now()) is None
    limiter.record_failure(clock.now())
    assert limiter.locked_for(clock.now()) is not None


def test_limiter_reports_the_time_left_of_the_lock() -> None:
    clock = FakeClock(START)
    limiter = FailureLimiter()
    for _ in range(5):
        limiter.record_failure(clock.now())
    clock.advance(timedelta(seconds=45))
    assert limiter.locked_for(clock.now()) == timedelta(seconds=15)


def test_limiter_lock_lasts_exactly_the_duration() -> None:
    clock = FakeClock(START)
    limiter = FailureLimiter()
    for _ in range(5):
        limiter.record_failure(clock.now())
    clock.advance(timedelta(seconds=59))
    assert limiter.locked_for(clock.now()) == timedelta(seconds=1)
    clock.advance(timedelta(seconds=1))
    assert limiter.locked_for(clock.now()) is None


def test_limiter_count_restarts_from_zero_after_the_lock_expires() -> None:
    clock = FakeClock(START)
    limiter = FailureLimiter()
    for _ in range(5):
        limiter.record_failure(clock.now())
    clock.advance(timedelta(seconds=60))
    for _ in range(4):
        limiter.record_failure(clock.now())
        assert limiter.locked_for(clock.now()) is None
    limiter.record_failure(clock.now())
    assert limiter.locked_for(clock.now()) == timedelta(seconds=60)


def test_limiter_failures_during_a_lock_do_not_extend_it() -> None:
    clock = FakeClock(START)
    limiter = FailureLimiter()
    for _ in range(5):
        limiter.record_failure(clock.now())
    clock.advance(timedelta(seconds=30))
    for _ in range(10):
        limiter.record_failure(clock.now())
    assert limiter.locked_for(clock.now()) == timedelta(seconds=30)
    clock.advance(timedelta(seconds=30))
    assert limiter.locked_for(clock.now()) is None


def test_limiter_failures_during_a_lock_do_not_count_toward_the_next_lock() -> None:
    clock = FakeClock(START)
    limiter = FailureLimiter()
    for _ in range(5):
        limiter.record_failure(clock.now())
    clock.advance(timedelta(seconds=30))
    for _ in range(10):
        limiter.record_failure(clock.now())
    clock.advance(timedelta(seconds=30))
    limiter.record_failure(clock.now())
    assert limiter.locked_for(clock.now()) is None


def test_limiter_success_does_not_lift_an_active_lock() -> None:
    clock = FakeClock(START)
    limiter = FailureLimiter()
    for _ in range(5):
        limiter.record_failure(clock.now())
    limiter.record_success()
    assert limiter.locked_for(clock.now()) == timedelta(seconds=60)


def test_limiter_honours_custom_limit_and_lock() -> None:
    limiter = FailureLimiter(limit=2, lock=timedelta(seconds=10))
    limiter.record_failure(START)
    assert limiter.locked_for(START) is None
    limiter.record_failure(START)
    assert limiter.locked_for(START) == timedelta(seconds=10)


@given(st.lists(st.integers(min_value=0, max_value=200), max_size=40))
def test_limiter_lock_never_exceeds_the_duration(offsets: list[int]) -> None:
    limiter = FailureLimiter()
    for offset in sorted(offsets):
        now = START + timedelta(seconds=offset)
        limiter.record_failure(now)
        left = limiter.locked_for(now)
        assert left is None or timedelta(0) < left <= LOCK_DURATION
