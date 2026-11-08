"""Job and DeadLetter models: validation, attempt counting, exact JSON round trip."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from builders import NAIVE, NOW
from command_center.core.jobs import MAX_REASON_LENGTH, DeadLetter, Job
from command_center.core.windows import TimeWindow

WINDOW = TimeWindow(start=NOW, end=NOW + timedelta(days=1))


def make_job(**overrides: Any) -> Job:  # noqa: ANN401  (overrides are validated by pydantic)
    fields: dict[str, Any] = {
        "id": "job-1",
        "kind": "sync",
        "source": "canvas",
        "window": WINDOW,
        "correlation_id": "corr-1",
    }
    fields.update(overrides)
    return Job.model_validate(fields)


zones = st.sampled_from(
    [UTC, ZoneInfo("America/Denver"), ZoneInfo("Asia/Kolkata"), timezone(timedelta(hours=-3))]
)
instants = st.datetimes(
    min_value=datetime(2000, 1, 1),  # noqa: DTZ001  (naive bounds, zone attached below)
    max_value=datetime(2060, 1, 1),  # noqa: DTZ001
    timezones=zones,
)
texts = st.text(min_size=1, max_size=40)


@st.composite
def jobs(draw: st.DrawFn) -> Job:
    start = draw(instants)
    span = draw(st.timedeltas(min_value=timedelta(seconds=1), max_value=timedelta(days=40)))
    return make_job(
        id=draw(texts),
        kind=draw(texts),
        source=draw(texts),
        correlation_id=draw(texts),
        attempt=draw(st.integers(min_value=1, max_value=1000)),
        window=TimeWindow(start=start, end=start + span),
    )


def test_job_attempt_defaults_to_one() -> None:
    assert make_job().attempt == 1


def test_next_attempt_returns_copy_with_attempt_plus_one() -> None:
    job = make_job(attempt=3)

    following = job.next_attempt()

    assert following.attempt == 4
    assert job.attempt == 3
    assert following.model_copy(update={"attempt": 3}) == job


def test_job_is_frozen() -> None:
    job = make_job()

    with pytest.raises(ValidationError):
        job.attempt = 2  # pyright: ignore[reportAttributeAccessIssue]


def test_job_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        make_job(surprise="x")


@pytest.mark.parametrize("field", ["id", "kind", "source", "correlation_id"])
def test_job_rejects_empty_text_field(field: str) -> None:
    with pytest.raises(ValidationError):
        make_job(**{field: ""})


@pytest.mark.parametrize("attempt", [0, -1])
def test_job_rejects_attempt_below_one(attempt: int) -> None:
    with pytest.raises(ValidationError):
        make_job(attempt=attempt)


def test_job_exact_json_round_trip_for_a_known_job() -> None:
    job = make_job(attempt=2)

    assert Job.model_validate_json(job.model_dump_json()) == job


@given(jobs())
def test_job_json_round_trip_is_exact(job: Job) -> None:
    restored = Job.model_validate_json(job.model_dump_json())

    # Not `restored == job`: Python never treats a ZoneInfo datetime in an ambiguous local hour
    # (DST fall-back) as equal to the same instant under another tzinfo, which JSON reloading is.
    assert restored.model_dump_json() == job.model_dump_json()
    assert restored.model_dump(exclude={"window"}) == job.model_dump(exclude={"window"})
    assert restored.window.start.astimezone(UTC) == job.window.start.astimezone(UTC)
    assert restored.window.end.astimezone(UTC) == job.window.end.astimezone(UTC)


@given(jobs())
def test_next_attempt_only_changes_attempt(job: Job) -> None:
    following = job.next_attempt()

    assert following.attempt == job.attempt + 1
    assert following.model_dump(exclude={"attempt"}) == job.model_dump(exclude={"attempt"})


def test_dead_letter_holds_job_reason_and_time() -> None:
    letter = DeadLetter(job=make_job(), reason="token rejected (401)", failed_at=NOW)

    assert letter.job.id == "job-1"
    assert letter.reason == "token rejected (401)"
    assert letter.failed_at == NOW


def test_dead_letter_rejects_naive_failed_at() -> None:
    with pytest.raises(ValidationError):
        DeadLetter(job=make_job(), reason="boom", failed_at=NAIVE)


def test_dead_letter_is_frozen_and_forbids_extras() -> None:
    letter = DeadLetter(job=make_job(), reason="boom", failed_at=NOW)

    with pytest.raises(ValidationError):
        letter.reason = "other"  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(ValidationError):
        DeadLetter.model_validate(
            {"job": make_job().model_dump(), "reason": "x", "failed_at": NOW, "extra": 1}
        )


def test_dead_letter_json_round_trip_is_exact() -> None:
    letter = DeadLetter(job=make_job(attempt=5), reason="boom", failed_at=NOW)

    assert DeadLetter.model_validate_json(letter.model_dump_json()) == letter


def test_max_reason_length_is_300() -> None:
    assert MAX_REASON_LENGTH == 300
