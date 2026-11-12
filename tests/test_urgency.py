"""Explainable urgency (decision 0370): each reason by example, invariants by seeded property."""

from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from builders import NAIVE_INSTANTS, NOW, make_event
from command_center.core.urgency import MAX_PRIORITY, MIN_PRIORITY, Urgency, assess, task_items

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
FIXED = settings(derandomize=True, max_examples=200, deadline=None)


def points(result: Urgency) -> dict[str, int]:
    return {reason.code: reason.points for reason in result.reasons}


def due(offset: timedelta, **fields: object) -> Urgency:
    return assess(make_event(kind="assignment", due=NOW + offset, **fields), NOW)


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (HOUR, 7),
        (6 * HOUR, 7),
        (6 * HOUR + timedelta(seconds=1), 6),
        (24 * HOUR, 6),
        (24 * HOUR + timedelta(seconds=1), 5),
        (48 * HOUR, 5),
        (48 * HOUR + timedelta(seconds=1), 3),
        (7 * DAY, 3),
        (7 * DAY + timedelta(seconds=1), 1),
        (14 * DAY, 1),
    ],
)
def test_due_time_adds_the_points_of_its_band(offset: timedelta, expected: int) -> None:
    assert points(due(offset)) == {"due": expected}


def test_a_due_time_beyond_two_weeks_adds_nothing_and_says_so() -> None:
    result = due(15 * DAY)
    assert (result.priority, result.score) == (1, 0)
    assert [r.code for r in result.reasons] == ["none"]


def test_overdue_adds_eight_points() -> None:
    assert points(due(-HOUR)) == {"overdue": 8}


def test_overdue_two_days_or_more_adds_one_more() -> None:
    assert points(due(-2 * DAY)) == {"overdue": 8, "overdue_long": 1}


def test_a_task_you_added_yourself_adds_a_point() -> None:
    event = make_event(kind="task", source="local", due=NOW + 10 * DAY)
    assert points(assess(event, NOW)) == {"due": 1, "manual": 1}


def test_a_task_from_another_source_is_not_manual() -> None:
    event = make_event(kind="task", source="canvas", due=NOW + 10 * DAY)
    assert "manual" not in points(assess(event, NOW))


@pytest.mark.parametrize(
    ("status", "waited", "expected"),
    [
        ("owed", HOUR, {"reply_owed": 3}),
        ("owed", 24 * HOUR, {"reply_owed": 3, "reply_age": 1}),
        ("overdue", 72 * HOUR, {"reply_overdue": 5, "reply_age": 2}),
        ("overdue", 23 * HOUR, {"reply_overdue": 5}),
    ],
)
def test_an_owed_reply_adds_points_for_its_state_and_age(
    status: str, waited: timedelta, expected: dict[str, int]
) -> None:
    event = make_event(kind="email", status=status, start=NOW - waited)
    assert points(assess(event, NOW)) == expected


def test_an_email_with_no_reply_owed_scores_the_floor() -> None:
    result = assess(make_event(kind="email", start=NOW - 5 * DAY), NOW)
    assert (result.priority, result.score) == (1, 0)


@pytest.mark.parametrize(
    ("start_offset", "expected"),
    [(timedelta(minutes=30), {"event_now": 4}), (5 * HOUR, {"event_today": 2}), (30 * HOUR, {})],
)
def test_an_event_scores_by_how_soon_it_starts(
    start_offset: timedelta, expected: dict[str, int]
) -> None:
    event = make_event(kind="event", start=NOW + start_offset)
    assert {k: v for k, v in points(assess(event, NOW)).items() if k != "none"} == expected


def test_an_event_in_progress_scores_and_an_ended_one_does_not() -> None:
    running = make_event(kind="event", start=NOW - HOUR, end=NOW + HOUR)
    ended = make_event(kind="event", start=NOW - 2 * HOUR, end=NOW - HOUR)
    assert points(assess(running, NOW)) == {"event_now": 4}
    assert points(assess(ended, NOW)) == {"none": 0}


@pytest.mark.parametrize("offset", [-3 * DAY, HOUR])
def test_a_done_item_has_one_zero_point_reason_and_priority_one(offset: timedelta) -> None:
    result = due(offset, status="done", source="local")
    assert (result.priority, result.score, points(result)) == (1, 0, {"done": 0})


def test_estimated_duration_in_the_raw_fields_changes_nothing() -> None:
    plain = due(5 * HOUR)
    padded = due(5 * HOUR, raw={"estimated_minutes": 600, "ai_estimate": 900})
    assert plain == padded


def test_every_reason_has_a_plain_sentence() -> None:
    result = due(-3 * DAY, source="local")
    assert [r.text for r in result.reasons] == ["Overdue by 3 days", "Overdue for two days or more"]
    assert all(r.text and r.text[0].isupper() and not r.text.endswith(":") for r in result.reasons)


@pytest.mark.parametrize("naive", NAIVE_INSTANTS)
def test_a_naive_now_is_refused(naive: object) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        assess(make_event(kind="task"), naive)  # type: ignore[arg-type]


def test_a_local_task_overdue_for_days_reaches_ten() -> None:
    event = make_event(kind="task", source="local", due=NOW - 3 * DAY)
    result = assess(event, NOW)
    assert result.priority == MAX_PRIORITY


kinds = st.sampled_from(["event", "assignment", "email", "weather", "task"])
statuses = st.sampled_from([None, "done", "owed", "overdue", "other"])
sources = st.sampled_from(["canvas", "local", "gmail"])
offsets = st.integers(min_value=-40 * 24 * 3600, max_value=40 * 24 * 3600).map(
    lambda s: timedelta(seconds=s)
)


@FIXED
@given(kinds, statuses, sources, offsets, offsets)
def test_the_score_is_clamped_and_the_reasons_sum_to_it(
    kind: str, status: str | None, source: str, due_offset: timedelta, start_offset: timedelta
) -> None:
    event = make_event(
        kind=kind,
        status=status,
        source=source,
        due=NOW + due_offset,
        start=NOW + start_offset,
        end=NOW + start_offset + HOUR,
    )
    result = assess(event, NOW)
    assert MIN_PRIORITY <= result.priority <= MAX_PRIORITY
    assert result.score == sum(r.points for r in result.reasons)
    assert result.priority == max(MIN_PRIORITY, min(MAX_PRIORITY, result.score))
    assert result == assess(event, NOW)


@FIXED
@given(st.sampled_from(["assignment", "task"]), sources, offsets, offsets)
def test_a_nearer_due_time_never_lowers_the_score(
    kind: str, source: str, first: timedelta, second: timedelta
) -> None:
    near, far = sorted((first, second))
    nearer = assess(make_event(kind=kind, source=source, due=NOW + near), NOW)
    farther = assess(make_event(kind=kind, source=source, due=NOW + far), NOW)
    assert nearer.score >= farther.score


@FIXED
@given(st.sampled_from(["assignment", "task"]), sources, offsets, offsets)
def test_overdue_scores_at_least_as_high_as_anything_due_within_48_hours(
    kind: str, source: str, late: timedelta, soon: timedelta
) -> None:
    overdue = assess(
        make_event(kind=kind, source=source, due=NOW - abs(late) - timedelta(seconds=1)), NOW
    )
    within = assess(make_event(kind=kind, source=source, due=NOW + abs(soon) % (48 * HOUR)), NOW)
    assert overdue.score >= within.score


def test_tasks_are_ranked_by_priority_then_due_with_undated_last_and_events_left_out() -> None:
    items = [
        make_event(id="far", kind="assignment", due=NOW + 20 * DAY),
        make_event(id="late", kind="assignment", due=NOW - HOUR),
        make_event(id="soon-b", kind="assignment", due=NOW + 40 * HOUR),
        make_event(id="soon-a", kind="task", due=NOW + 30 * HOUR),
        make_event(id="mail", kind="email", status="owed", start=NOW - HOUR),
        make_event(id="meeting", kind="event", start=NOW + HOUR),
        make_event(id="undated", kind="task"),
    ]
    ranked = task_items(items, NOW)
    assert [t.id for t in ranked] == ["late", "soon-a", "soon-b", "mail", "far", "undated"]
    assert ranked[0].done is False
