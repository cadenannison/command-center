"""Priority 1-10 derived from the 0-100 urgency score (docs/contracts/core.md)."""

from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from builders import NOW, make_event
from command_center.core.priority import MAX_PRIORITY, priority
from command_center.core.schema import Event
from command_center.core.scoring import urgency

deterministic = settings(derandomize=True)


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0, None), (1, 1), (10, 1), (11, 2), (50, 5), (90, 9), (91, 10), (100, 10)],
)
def test_boundary_table(score: int, expected: int | None) -> None:
    assert priority(score) == expected


def test_done_with_high_urgency_has_no_priority() -> None:
    assert priority(100, done=True) is None


def test_max_priority_is_ten() -> None:
    assert MAX_PRIORITY == 10


@deterministic
@given(st.integers(min_value=1, max_value=100))
def test_priority_is_bounded(score: int) -> None:
    result = priority(score)
    assert result is not None
    assert 1 <= result <= MAX_PRIORITY


@deterministic
@given(st.integers(min_value=1, max_value=100), st.integers(min_value=1, max_value=100))
def test_priority_never_decreases_with_urgency(a: int, b: int) -> None:
    low, high = sorted((a, b))
    assert priority(low) <= priority(high)  # type: ignore[operator]


@deterministic
@given(st.integers(min_value=0, max_value=100))
def test_done_has_no_priority_at_any_urgency(score: int) -> None:
    assert priority(score, done=True) is None


@deterministic
@given(done=st.booleans())
def test_zero_urgency_has_no_priority(*, done: bool) -> None:
    assert priority(0, done=done) is None


def test_event_priority_follows_its_urgency() -> None:
    assert make_event(urgency=91).priority == 10
    assert make_event(urgency=40).priority == 4
    assert make_event(urgency=0).priority is None


def test_done_event_has_no_priority() -> None:
    assert make_event(urgency=100, status="done").priority is None


def test_dump_includes_priority() -> None:
    event = make_event(urgency=70)
    assert event.model_dump()["priority"] == 7
    assert '"priority":7' in event.model_dump_json()


def test_dump_has_null_priority_when_none() -> None:
    event = make_event(urgency=0)
    assert event.model_dump()["priority"] is None
    assert '"priority":null' in event.model_dump_json()


def test_validating_a_dump_with_priority_still_works() -> None:
    event = make_event(urgency=70)
    again = Event.model_validate(event.model_dump())
    assert again == event
    assert again.priority == 7


def test_priority_does_not_affect_equality() -> None:
    assert make_event(urgency=70) == make_event(urgency=70)
    assert make_event(urgency=70) != make_event(urgency=71)


def test_overdue_assignment_is_priority_ten() -> None:
    event = make_event(kind="assignment", due=NOW - timedelta(days=1))
    assert priority(urgency(event, NOW)) == 10


def test_done_assignment_has_no_priority() -> None:
    event = make_event(kind="assignment", due=NOW - timedelta(days=1), status="done")
    assert priority(urgency(event, NOW), done=event.status == "done") is None


def test_ended_event_has_no_priority() -> None:
    event = make_event(kind="event", start=NOW - timedelta(hours=3), end=NOW - timedelta(hours=2))
    assert priority(urgency(event, NOW)) is None
