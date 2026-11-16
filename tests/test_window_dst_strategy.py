"""DST edges for TimeWindow in America/Denver and for the jobs() strategy that builds windows."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import ValidationError

from command_center.core.jobs import Job
from command_center.core.windows import TimeWindow
from test_jobs import instants, jobs, window_after

DENVER = ZoneInfo("America/Denver")
FALL_BACK_SECOND_PASS = datetime(2028, 11, 5, 1, 0, fold=1, tzinfo=DENVER)  # 08:00 UTC
SPRING_FORWARD_LAST_SECOND = datetime(2028, 3, 12, 1, 59, 59, tzinfo=DENVER)  # 08:59:59 UTC
PLAIN_NOON = datetime(2028, 7, 1, 12, 0, tzinfo=DENVER)
spans = st.timedeltas(min_value=timedelta(seconds=1), max_value=timedelta(days=40))


@given(start=instants, span=spans)
@example(start=FALL_BACK_SECOND_PASS, span=timedelta(seconds=1))  # the replayed failing example
@example(start=FALL_BACK_SECOND_PASS, span=timedelta(hours=1))
@example(start=SPRING_FORWARD_LAST_SECOND, span=timedelta(seconds=1))
@example(start=SPRING_FORWARD_LAST_SECOND, span=timedelta(hours=2))
@example(start=PLAIN_NOON, span=timedelta(days=1))
def test_elapsed_span_window_is_accepted_and_exactly_span_long(
    start: datetime, span: timedelta
) -> None:
    window = window_after(start, span)
    assert window.end.astimezone(UTC) - window.start.astimezone(UTC) == span


@given(jobs())
def test_jobs_strategy_yields_windows_with_end_after_start_in_utc(job: Job) -> None:
    window = job.window
    assert window.end.astimezone(UTC) > window.start.astimezone(UTC)


def test_window_rejects_reversed_pair_across_the_fall_back_hour() -> None:
    wall_clock_end = FALL_BACK_SECOND_PASS.replace(fold=0) + timedelta(seconds=1)  # 07:00:01 UTC
    with pytest.raises(ValidationError, match="end must be after start"):
        TimeWindow(start=FALL_BACK_SECOND_PASS, end=wall_clock_end)


def test_window_accepts_pair_that_wall_clock_reads_as_reversed() -> None:
    first_pass = datetime(2028, 11, 5, 1, 30, fold=0, tzinfo=DENVER)  # 07:30 UTC
    second_pass_earlier_wall = datetime(2028, 11, 5, 1, 10, fold=1, tzinfo=DENVER)  # 08:10 UTC
    window = TimeWindow(start=first_pass, end=second_pass_earlier_wall)
    assert window.contains(datetime(2028, 11, 5, 8, 0, tzinfo=UTC))
