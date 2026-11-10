"""The plain-language reason for a priority, and its agreement with the score."""

from datetime import datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from builders import NAIVE_INSTANTS, NOW, make_event
from command_center.core.scoring import explain, urgency

MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
KINDS = ["event", "assignment", "email", "weather", "task"]
OFFSETS = st.timedeltas(min_value=timedelta(days=-400), max_value=timedelta(days=400))


@pytest.mark.parametrize("kind", KINDS)
def test_done_item_says_done_for_every_kind(kind: str) -> None:
    event = make_event(kind=kind, status="done", due=NOW + HOUR)

    assert explain(event, NOW) == "Done, no priority"


def test_weather_says_no_priority() -> None:
    assert explain(make_event(kind="weather"), NOW) == "Weather, no priority"


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (30 * MINUTE, "Due in 30 minutes, not submitted"),
        (MINUTE, "Due in 1 minute, not submitted"),
        (timedelta(0), "Due in 1 minute, not submitted"),
        (59 * MINUTE, "Due in 59 minutes, not submitted"),
        (60 * MINUTE, "Due in 1 hour, not submitted"),
        (18 * HOUR, "Due in 18 hours, not submitted"),
        (47 * HOUR + 59 * MINUTE, "Due in 47 hours, not submitted"),
        (48 * HOUR, "Due in 2 days, not submitted"),
        (timedelta(days=3, hours=5), "Due in 3 days, not submitted"),
        (-30 * MINUTE, "Overdue by 30 minutes, not submitted"),
        (-HOUR, "Overdue by 1 hour, not submitted"),
        (-timedelta(days=2), "Overdue by 2 days, not submitted"),
    ],
)
def test_assignment_reason_by_time_to_due(offset: timedelta, expected: str) -> None:
    event = make_event(kind="assignment", due=NOW + offset)

    assert explain(event, NOW) == expected


def test_task_reason_says_not_done() -> None:
    event = make_event(kind="task", due=NOW + 18 * HOUR)

    assert explain(event, NOW) == "Due in 18 hours, not done"


def test_overdue_task_reason_says_not_done() -> None:
    event = make_event(kind="task", due=NOW - 3 * HOUR)

    assert explain(event, NOW) == "Overdue by 3 hours, not done"


@pytest.mark.parametrize("kind", ["assignment", "task"])
def test_item_without_due_date_says_so(kind: str) -> None:
    assert explain(make_event(kind=kind), NOW) == "No due date"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("overdue", "Reply overdue"),
        ("owed", "Reply owed"),
        (None, "No reply owed"),
        ("open", "No reply owed"),
    ],
)
def test_email_reason_by_status(status: str | None, expected: str) -> None:
    assert explain(make_event(kind="email", status=status), NOW) == expected


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (NOW - 3 * HOUR, NOW - MINUTE, "Already over"),
        (None, NOW - MINUTE, "Already over"),
        (NOW - MINUTE, None, "Already over"),
        (None, None, "No start time"),
        (NOW, None, "In progress"),
        (NOW - HOUR, NOW + HOUR, "In progress"),
        (NOW, NOW, "In progress"),
        (NOW + HOUR, None, "Starts in 1 hour"),
        (NOW + 30 * MINUTE, NOW + 2 * HOUR, "Starts in 30 minutes"),
        (NOW + 2 * HOUR, None, "Starts in 2 hours"),
        (NOW + 3 * HOUR, None, "Later today"),
        (NOW + 12 * HOUR, None, "Not today"),
        (NOW + timedelta(days=3), NOW + timedelta(days=3, hours=1), "Not today"),
        (NOW - HOUR, NOW + 25 * HOUR, "Long event: in progress"),
        (NOW + HOUR, NOW + 30 * HOUR, "Long event: starts in 1 hour"),
        (NOW + 3 * HOUR, NOW + 40 * HOUR, "Later today"),
    ],
)
def test_event_reason_by_start_and_end(
    start: datetime | None, end: datetime | None, expected: str
) -> None:
    event = make_event(kind="event", start=start, end=end)

    assert explain(event, NOW) == expected


@pytest.mark.parametrize("now", NAIVE_INSTANTS)
@pytest.mark.parametrize("kind", KINDS)
def test_naive_now_is_a_value_error_for_every_kind(kind: str, now: datetime) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        explain(make_event(kind=kind), now)


def test_explain_is_deterministic() -> None:
    event = make_event(kind="assignment", due=NOW + 5 * HOUR)

    assert explain(event, NOW) == explain(event, NOW)


@given(
    kind=st.sampled_from(KINDS),
    status=st.sampled_from([None, "done", "overdue", "owed", "open"]),
    due_offset=st.one_of(st.none(), OFFSETS),
    start_offset=st.one_of(st.none(), OFFSETS),
    length=st.one_of(
        st.none(), st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=30))
    ),
)
def test_reason_is_short_and_has_no_trailing_period(
    kind: str,
    status: str | None,
    due_offset: timedelta | None,
    start_offset: timedelta | None,
    length: timedelta | None,
) -> None:
    start = None if start_offset is None else NOW + start_offset
    event = make_event(
        kind=kind,
        status=status,
        due=None if due_offset is None else NOW + due_offset,
        start=start,
        end=None if start is None or length is None else start + length,
    )

    reason = explain(event, NOW)

    assert 1 <= len(reason) <= 80
    assert not reason.endswith(".")


@given(
    kind=st.sampled_from(["assignment", "task"]),
    due_offset=st.one_of(st.none(), OFFSETS),
)
def test_reason_says_overdue_exactly_when_the_score_is_100(
    kind: str, due_offset: timedelta | None
) -> None:
    event = make_event(kind=kind, due=None if due_offset is None else NOW + due_offset)

    assert explain(event, NOW).startswith("Overdue") == (urgency(event, NOW) == 100)


@given(kind=st.sampled_from(KINDS), due_offset=OFFSETS)
def test_done_reason_never_depends_on_the_dates(kind: str, due_offset: timedelta) -> None:
    event = make_event(kind=kind, status="done", due=NOW + due_offset, start=NOW + due_offset)

    assert explain(event, NOW) == "Done, no priority"
    assert urgency(event, NOW) == 0
