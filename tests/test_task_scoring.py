"""Scoring of local tasks, and the rule that a done item scores 0 for every kind."""

from datetime import timedelta

from hypothesis import given
from hypothesis import strategies as st

from builders import NOW, make_event
from command_center.core.scoring import urgency

KINDS = ["event", "assignment", "email", "weather", "task"]
OFFSETS = st.timedeltas(min_value=timedelta(days=-400), max_value=timedelta(days=400))


@given(offset=OFFSETS, status=st.sampled_from([None, "open", "submitted"]))
def test_task_scores_like_an_assignment_with_the_same_due(
    offset: timedelta, status: str | None
) -> None:
    task = make_event(kind="task", due=NOW + offset, status=status)
    assignment = make_event(kind="assignment", due=NOW + offset, status=status)

    assert urgency(task, NOW) == urgency(assignment, NOW)


def test_task_without_due_date_scores_lowest_open_band() -> None:
    assert urgency(make_event(kind="task"), NOW) == 10


def test_overdue_task_scores_100() -> None:
    assert urgency(make_event(kind="task", due=NOW - timedelta(minutes=1)), NOW) == 100


@given(
    kind=st.sampled_from(KINDS),
    due_offset=OFFSETS,
    start_offset=OFFSETS,
    length=st.one_of(st.none(), st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=3))),
)
def test_done_item_scores_zero_for_every_kind(
    kind: str, due_offset: timedelta, start_offset: timedelta, length: timedelta | None
) -> None:
    start = NOW + start_offset
    event = make_event(
        kind=kind,
        status="done",
        due=NOW + due_offset,
        start=start,
        end=None if length is None else start + length,
    )

    assert urgency(event, NOW) == 0


def test_done_email_scores_zero_although_other_statuses_score() -> None:
    assert urgency(make_event(kind="email", status="done"), NOW) == 0
    assert urgency(make_event(kind="email", status="owed"), NOW) == 50
