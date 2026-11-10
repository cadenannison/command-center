"""Event schema: frozen, timezone-aware, stable ids."""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from builders import NOW, make_event
from command_center.core.schema import (
    Event,
    SecretStatus,
    ValidationResult,
    event_id,
    secret_status,
)

NAIVE = datetime(2026, 11, 7, 12, 0)  # noqa: DTZ001  (the point of these tests)


def test_event_defaults_to_local_user_and_zero_urgency() -> None:
    event = make_event()

    assert event.user_id == "local"
    assert event.urgency == 0
    assert event.start is None
    assert event.raw == {}


def test_event_is_frozen() -> None:
    event = make_event()

    with pytest.raises(ValidationError):
        event.title = "changed"  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize("field", ["start", "end", "due", "fetched_at"])
def test_event_rejects_naive_datetimes(field: str) -> None:
    with pytest.raises(ValidationError):
        make_event(**{field: NAIVE})


def test_event_accepts_aware_datetimes() -> None:
    event = make_event(start=NOW, end=NOW, due=NOW)

    assert event.start == NOW
    assert event.fetched_at.tzinfo is not None


@pytest.mark.parametrize("urgency", [-1, 101])
def test_event_rejects_urgency_outside_0_to_100(urgency: int) -> None:
    with pytest.raises(ValidationError):
        make_event(urgency=urgency)


@pytest.mark.parametrize("urgency", [0, 100])
def test_event_accepts_urgency_bounds(urgency: int) -> None:
    assert make_event(urgency=urgency).urgency == urgency


def test_event_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        make_event(kind="bogus")


@pytest.mark.parametrize("kind", ["event", "assignment", "email", "weather", "task"])
def test_event_accepts_each_kind(kind: str) -> None:
    assert make_event(kind=kind).kind == kind


def test_event_round_trips_through_json() -> None:
    event = make_event(kind="assignment", due=NOW, status="open", raw={"a": 1}, link="https://x.y/")

    assert Event.model_validate_json(event.model_dump_json()) == event


def test_event_id_is_32_lowercase_hex_chars() -> None:
    assert re.fullmatch(r"[0-9a-f]{32}", event_id("canvas", "123"))


def test_event_id_is_deterministic() -> None:
    assert event_id("canvas", "123") == event_id("canvas", "123")


def test_event_id_differs_by_source_and_source_id() -> None:
    assert event_id("canvas", "123") != event_id("gmail", "123")
    assert event_id("canvas", "123") != event_id("canvas", "124")


def test_event_id_does_not_collide_across_the_source_boundary() -> None:
    assert event_id("a:b", "c") != event_id("a", "b:c")
    assert event_id("ab", "c") != event_id("a", "bc")


def test_event_id_matches_known_digest() -> None:
    # sha256 of source + NUL + source_id. Ids are persisted, so a change would orphan stored rows.
    assert event_id("canvas", "123") == "cbe28e5b362f05a19359310e74509eca"


def test_validation_result_defaults_to_no_updated_creds() -> None:
    result = ValidationResult(ok=True, message="fine")

    assert result.updated_creds is None


def test_validation_result_repr_and_str_do_not_reveal_updated_creds() -> None:
    result = ValidationResult(ok=True, message="fine", updated_creds={"token": "fake-s3cr3t-token"})

    assert "fake-s3cr3t-token" not in repr(result)
    assert "fake-s3cr3t-token" not in str(result)
    assert result.updated_creds == {"token": "fake-s3cr3t-token"}


def test_secret_status_reports_set_and_last4() -> None:
    status = SecretStatus(set=True, last4="wxyz")

    assert status.set is True
    assert status.last4 == "wxyz"


def test_secret_status_last4_may_be_absent() -> None:
    assert SecretStatus(set=True).last4 is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", SecretStatus(set=True, last4=None)),
        ("fake-12", SecretStatus(set=True, last4=None)),
        ("fake-123", SecretStatus(set=True, last4="-123")),
        ("fake-a-much-longer-token-9876", SecretStatus(set=True, last4="9876")),
    ],
)
def test_secret_status_of_a_value_hides_last4_below_eight_characters(
    value: str, expected: SecretStatus
) -> None:
    assert secret_status(value) == expected


@given(st.text(min_size=8))
def test_secret_status_never_reveals_more_than_the_last_four_characters(value: str) -> None:
    status = secret_status(value)

    assert status.last4 == value[-4:]
    assert len(status.last4 or "") == 4


def test_aware_non_utc_datetime_is_accepted() -> None:
    stamp = datetime(2026, 11, 7, 12, 0, tzinfo=ZoneInfo("America/Denver"))

    assert make_event(start=stamp).start == stamp
    assert make_event(start=stamp).start == datetime(2026, 11, 7, 19, 0, tzinfo=UTC)
