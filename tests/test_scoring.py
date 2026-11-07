"""Urgency scoring table (docs/contracts/core.md) and its invariants."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from builders import NAIVE_INSTANTS, NOW, make_event
from command_center.core.scoring import urgency

HOUR = timedelta(hours=1)


@pytest.mark.parametrize(
    ("due_offset", "expected"),
    [
        (-timedelta(seconds=1), 100),
        (-timedelta(days=30), 100),
        (timedelta(0), 90),
        (24 * HOUR, 90),
        (24 * HOUR + timedelta(seconds=1), 70),
        (72 * HOUR, 70),
        (72 * HOUR + timedelta(seconds=1), 40),
        (timedelta(days=7), 40),
        (timedelta(days=7, seconds=1), 10),
        (timedelta(days=90), 10),
    ],
)
def test_assignment_urgency_by_time_to_due(due_offset: timedelta, expected: int) -> None:
    event = make_event(kind="assignment", due=NOW + due_offset)

    assert urgency(event, NOW) == expected


@pytest.mark.parametrize("offset", [-timedelta(days=3), timedelta(0), timedelta(days=3)])
def test_done_assignment_scores_zero(offset: timedelta) -> None:
    event = make_event(kind="assignment", due=NOW + offset, status="done")

    assert urgency(event, NOW) == 0


def test_assignment_with_other_status_is_not_done() -> None:
    event = make_event(kind="assignment", due=NOW - HOUR, status="submitted")

    assert urgency(event, NOW) == 100


def test_assignment_without_due_date_scores_lowest_open_band() -> None:
    assert urgency(make_event(kind="assignment"), NOW) == 10


@pytest.mark.parametrize(
    ("start_offset", "expected"),
    [
        (timedelta(minutes=1), 60),
        (2 * HOUR, 60),
        (2 * HOUR + timedelta(seconds=1), 40),
        (11 * HOUR + timedelta(minutes=59), 40),
        (12 * HOUR, 10),
        (timedelta(days=3), 10),
    ],
)
def test_event_urgency_by_start(start_offset: timedelta, expected: int) -> None:
    event = make_event(kind="event", start=NOW + start_offset)

    assert urgency(event, NOW) == expected


def at(offset: timedelta) -> datetime:
    return NOW + offset


@pytest.mark.parametrize(
    ("start_offset", "end_offset", "expected"),
    [
        # ended: end < now, whatever the start
        (-2 * HOUR, -timedelta(seconds=1), 0),
        (HOUR, -timedelta(seconds=1), 0),
        # end == now counts as ongoing
        (-HOUR, timedelta(0), 60),
        (-HOUR, timedelta(seconds=1), 60),
        (-timedelta(days=2), timedelta(hours=1), 40),
        # not started yet but within 2h, with an end
        (timedelta(minutes=30), 2 * HOUR, 60),
        (2 * HOUR, 3 * HOUR, 60),
        (2 * HOUR + timedelta(seconds=1), 3 * HOUR, 40),
    ],
)
def test_event_with_an_end_is_scored_by_ended_ongoing_or_upcoming(
    start_offset: timedelta, end_offset: timedelta, expected: int
) -> None:
    event = make_event(kind="event", start=at(start_offset), end=at(end_offset))

    assert urgency(event, NOW) == expected


@pytest.mark.parametrize(
    ("start_offset", "expected"),
    [
        (-timedelta(seconds=1), 0),
        (-timedelta(days=5), 0),
        (timedelta(0), 60),
        (timedelta(seconds=1), 60),
    ],
)
def test_event_without_an_end_has_ended_once_its_start_has_passed(
    start_offset: timedelta, expected: int
) -> None:
    assert urgency(make_event(kind="event", start=at(start_offset)), NOW) == expected


@pytest.mark.parametrize(
    ("start_offset", "end_offset", "expected"),
    [
        # span of exactly 24h or more: 40 instead of 60
        (-HOUR, 23 * HOUR, 40),
        (-HOUR, 23 * HOUR + timedelta(seconds=1), 40),
        (HOUR, 25 * HOUR, 40),
        (-timedelta(days=3), timedelta(days=3), 40),
        # span just under 24h stays 60
        (-HOUR, 23 * HOUR - timedelta(seconds=1), 60),
        (HOUR, 25 * HOUR - timedelta(seconds=1), 60),
    ],
)
def test_event_spanning_a_day_or_more_scores_40_while_active_or_imminent(
    start_offset: timedelta, end_offset: timedelta, expected: int
) -> None:
    event = make_event(kind="event", start=at(start_offset), end=at(end_offset))

    assert urgency(event, NOW) == expected


def test_long_span_starting_later_today_keeps_the_later_today_score() -> None:
    event = make_event(kind="event", start=at(5 * HOUR), end=at(5 * HOUR + timedelta(days=2)))

    assert urgency(event, NOW) == 40


def test_long_span_starting_after_today_scores_10() -> None:
    event = make_event(kind="event", start=at(timedelta(days=2)), end=at(timedelta(days=5)))

    assert urgency(event, NOW) == 10


def test_ended_long_span_scores_zero() -> None:
    event = make_event(kind="event", start=at(-timedelta(days=5)), end=at(-HOUR))

    assert urgency(event, NOW) == 0


def test_event_ended_check_compares_instants_in_utc() -> None:
    denver = ZoneInfo("America/Denver")
    now = datetime(2026, 11, 1, 1, 45, tzinfo=denver, fold=0)  # MDT
    end = datetime(2026, 11, 1, 1, 30, tzinfo=denver, fold=1)  # MST, 45 minutes after now
    start = datetime(2026, 11, 1, 1, 0, tzinfo=denver, fold=0)

    assert urgency(make_event(kind="event", start=start, end=end), now) == 60


def test_event_without_start_but_with_a_past_end_has_ended() -> None:
    assert urgency(make_event(kind="event", end=NOW - HOUR), NOW) == 0


def test_event_without_start_scores_lowest_band() -> None:
    assert urgency(make_event(kind="event"), NOW) == 10


def test_event_today_is_judged_in_the_timezone_of_now() -> None:
    denver = ZoneInfo("America/Denver")
    now = datetime(2026, 11, 7, 20, 0, tzinfo=denver)
    same_local_day = datetime(2026, 11, 7, 23, 30, tzinfo=denver)
    next_local_day = datetime(2026, 11, 8, 0, 30, tzinfo=denver)

    assert urgency(make_event(start=same_local_day), now) == 40
    # Same UTC date as `now` (Nov 8) but a different local date, so UTC-based logic would say 40.
    assert urgency(make_event(start=next_local_day), now) == 10


@pytest.mark.parametrize(
    ("status", "expected"),
    [("overdue", 75), ("owed", 50), ("read", 5), ("", 5), (None, 5)],
)
def test_email_urgency_by_status(status: str | None, expected: int) -> None:
    assert urgency(make_event(kind="email", status=status), NOW) == expected


def test_weather_scores_zero() -> None:
    assert urgency(make_event(kind="weather", start=NOW), NOW) == 0


def test_urgency_ignores_the_stored_urgency_field() -> None:
    event = make_event(kind="email", status="owed", urgency=99)

    assert urgency(event, NOW) == 50


@given(
    kind=st.sampled_from(["event", "assignment", "email", "weather"]),
    status=st.sampled_from([None, "done", "overdue", "owed", "open"]),
    due_offset=st.timedeltas(min_value=timedelta(days=-400), max_value=timedelta(days=400)),
    start_offset=st.timedeltas(min_value=timedelta(days=-400), max_value=timedelta(days=400)),
    length=st.one_of(
        st.none(), st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=30))
    ),
)
def test_urgency_always_within_0_to_100(
    kind: str,
    status: str | None,
    due_offset: timedelta,
    start_offset: timedelta,
    length: timedelta | None,
) -> None:
    start = NOW + start_offset
    event = make_event(
        kind=kind,
        status=status,
        due=NOW + due_offset,
        start=start,
        end=None if length is None else start + length,
    )

    assert 0 <= urgency(event, NOW) <= 100


@given(
    earlier=st.timedeltas(min_value=timedelta(days=-400), max_value=timedelta(days=400)),
    gap=st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=400)),
    status=st.sampled_from([None, "open", "done"]),
)
def test_assignment_urgency_never_rises_as_due_moves_later(
    earlier: timedelta, gap: timedelta, status: str | None
) -> None:
    sooner = make_event(kind="assignment", status=status, due=NOW + earlier)
    later = make_event(kind="assignment", status=status, due=NOW + earlier + gap)

    assert urgency(later, NOW) <= urgency(sooner, NOW)


@given(
    offset=st.timedeltas(min_value=timedelta(days=-400), max_value=timedelta(days=400)),
    now_shift=st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=400)),
)
def test_assignment_urgency_never_falls_as_now_approaches_due(
    offset: timedelta, now_shift: timedelta
) -> None:
    event = make_event(kind="assignment", due=NOW + offset)

    assert urgency(event, NOW + now_shift) >= urgency(event, NOW)


DENVER = ZoneInfo("America/Denver")


def test_assignment_due_before_now_across_fall_back_is_not_overdue() -> None:
    # 01:30 MST (fold=1) is 45 minutes after 01:45 MDT (fold=0); wall clock says -15 minutes.
    now = datetime(2026, 11, 1, 1, 45, tzinfo=DENVER, fold=0)
    due = datetime(2026, 11, 1, 1, 30, tzinfo=DENVER, fold=1)

    assert urgency(make_event(kind="assignment", due=due), now) == 90


def test_assignment_due_25_real_hours_after_now_across_fall_back_scores_70() -> None:
    now = datetime(2026, 10, 31, 23, 0, tzinfo=DENVER)
    due = datetime(2026, 11, 1, 23, 0, tzinfo=DENVER)

    assert urgency(make_event(kind="assignment", due=due), now) == 70


def test_assignment_due_23_real_hours_30_after_now_across_spring_forward_scores_90() -> None:
    # 2026-03-08 02:00 MST jumps to 03:00 MDT: 24h30m of wall clock is only 23h30m of real time.
    now = datetime(2026, 3, 7, 12, 0, tzinfo=DENVER)
    due = datetime(2026, 3, 8, 12, 30, tzinfo=DENVER)

    assert urgency(make_event(kind="assignment", due=due), now) == 90


def test_event_start_beyond_two_real_hours_across_fall_back_scores_40() -> None:
    # Wall clock says 1h30m apart; really 2h30m because 01:00-02:00 happens twice.
    now = datetime(2026, 11, 1, 0, 30, tzinfo=DENVER)
    start = datetime(2026, 11, 1, 2, 0, tzinfo=DENVER, fold=1)

    assert urgency(make_event(kind="event", start=start), now) == 40


def test_event_start_within_two_real_hours_across_spring_forward_scores_60() -> None:
    # Wall clock says 2h30m apart; really 1h30m because 02:00-03:00 is skipped.
    now = datetime(2026, 3, 8, 0, 30, tzinfo=DENVER)
    start = datetime(2026, 3, 8, 3, 0, tzinfo=DENVER)

    assert urgency(make_event(kind="event", start=start), now) == 60


@given(
    start_offset=st.timedeltas(min_value=timedelta(days=-400), max_value=timedelta(days=400)),
    length=st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=30)),
)
def test_event_score_is_zero_exactly_when_the_event_has_ended(
    start_offset: timedelta, length: timedelta
) -> None:
    start = NOW + start_offset
    event = make_event(kind="event", start=start, end=start + length)

    assert (urgency(event, NOW) == 0) == (start + length < NOW)


@pytest.mark.parametrize("kind", ["event", "assignment", "email", "weather"])
@pytest.mark.parametrize("naive_now", NAIVE_INSTANTS, ids=["no-tzinfo", "no-utcoffset"])
def test_urgency_rejects_a_naive_now_instead_of_reading_the_host_timezone(
    kind: str, naive_now: datetime
) -> None:
    event = make_event(kind=kind, start=NOW, due=NOW)

    with pytest.raises(ValueError, match="timezone-aware"):
        urgency(event, naive_now)
