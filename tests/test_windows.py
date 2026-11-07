"""Window math: local-midnight boundaries, Monday weeks, DST safety."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from builders import NAIVE_INSTANTS, NOW, OffsetlessTz
from command_center.core.windows import TimeWindow, day_window, month_window, week_window

DENVER = ZoneInfo("America/Denver")
ZONES = [
    "UTC",
    "America/Denver",
    "America/New_York",
    "America/Havana",  # DST begins at local midnight, so 00:00 does not exist that day
    "Europe/London",
    "Australia/Lord_Howe",  # 30-minute DST shift
    "Asia/Kolkata",
    "Pacific/Auckland",
]
zones = st.sampled_from(ZONES).map(ZoneInfo)
dates = st.dates(min_value=date(2000, 1, 1), max_value=date(2060, 12, 31))


def as_utc(stamp: datetime) -> datetime:
    return stamp.astimezone(UTC)


def test_time_window_rejects_naive_datetimes() -> None:
    with pytest.raises(ValidationError):
        TimeWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2, tzinfo=UTC))  # noqa: DTZ001


def test_time_window_rejects_end_not_after_start() -> None:
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    with pytest.raises(ValidationError):
        TimeWindow(start=stamp, end=stamp)


def test_time_window_is_frozen() -> None:
    window = day_window(date(2026, 11, 7), DENVER)

    with pytest.raises(ValidationError):
        window.start = window.end  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]


def test_time_window_contains_is_half_open() -> None:
    window = day_window(date(2026, 11, 7), UTC)

    assert window.contains(window.start)
    assert window.contains(window.end - timedelta(microseconds=1))
    assert not window.contains(window.end)
    assert not window.contains(window.start - timedelta(microseconds=1))


def test_day_window_runs_local_midnight_to_next_local_midnight() -> None:
    window = day_window(date(2026, 11, 7), DENVER)

    assert window.start == datetime(2026, 11, 7, 0, 0, tzinfo=DENVER)
    assert window.end == datetime(2026, 11, 8, 0, 0, tzinfo=DENVER)


def test_day_window_is_23_hours_when_clocks_spring_forward() -> None:
    window = day_window(date(2026, 3, 8), DENVER)

    assert as_utc(window.end) - as_utc(window.start) == timedelta(hours=23)


def test_day_window_is_25_hours_when_clocks_fall_back() -> None:
    window = day_window(date(2026, 11, 1), DENVER)

    assert as_utc(window.end) - as_utc(window.start) == timedelta(hours=25)


def test_week_window_starts_on_monday_for_any_day_of_that_week() -> None:
    monday = date(2026, 11, 2)

    for offset in range(7):
        window = week_window(monday + timedelta(days=offset), DENVER)
        assert window.start == datetime(2026, 11, 2, tzinfo=DENVER)
        assert window.end == datetime(2026, 11, 9, tzinfo=DENVER)


def test_week_window_crossing_a_month_and_year_boundary() -> None:
    window = week_window(date(2026, 1, 1), UTC)  # a Thursday

    assert window.start == datetime(2025, 12, 29, tzinfo=UTC)
    assert window.end == datetime(2026, 1, 5, tzinfo=UTC)


def test_week_window_spanning_spring_forward_is_167_hours() -> None:
    window = week_window(date(2026, 3, 8), DENVER)

    assert as_utc(window.end) - as_utc(window.start) == timedelta(hours=167)


@pytest.mark.parametrize(
    ("day", "first", "after"),
    [
        (date(2026, 11, 17), date(2026, 11, 1), date(2026, 12, 1)),
        (date(2026, 12, 31), date(2026, 12, 1), date(2027, 1, 1)),
        (date(2024, 2, 29), date(2024, 2, 1), date(2024, 3, 1)),
    ],
)
def test_month_window_runs_first_of_month_to_first_of_next(
    day: date, first: date, after: date
) -> None:
    window = month_window(day, DENVER)

    assert window.start == datetime(first.year, first.month, first.day, tzinfo=DENVER)
    assert window.end == datetime(after.year, after.month, after.day, tzinfo=DENVER)


@given(day=dates, zone=zones)
def test_adjacent_days_are_ordered_and_contiguous(day: date, zone: ZoneInfo) -> None:
    today = day_window(day, zone)
    tomorrow = day_window(day + timedelta(days=1), zone)

    assert as_utc(today.start) < as_utc(today.end)
    assert as_utc(today.end) == as_utc(tomorrow.start)


@given(day=dates, zone=zones)
def test_adjacent_weeks_and_months_are_contiguous(day: date, zone: ZoneInfo) -> None:
    this_week = week_window(day, zone)
    next_week = week_window(day + timedelta(days=7), zone)
    this_month = month_window(day, zone)
    next_month = month_window(this_month.end.date() + timedelta(days=1), zone)

    assert as_utc(this_week.end) == as_utc(next_week.start)
    assert as_utc(this_month.end) == as_utc(next_month.start)


@given(day=dates, zone=zones)
def test_day_is_inside_its_week_and_month_and_week_starts_on_monday(
    day: date, zone: ZoneInfo
) -> None:
    day_w = day_window(day, zone)
    week_w = week_window(day, zone)
    month_w = month_window(day, zone)

    assert week_w.start.weekday() == 0
    assert as_utc(week_w.start) <= as_utc(day_w.start) < as_utc(day_w.end) <= as_utc(week_w.end)
    assert as_utc(month_w.start) <= as_utc(day_w.start) < as_utc(day_w.end) <= as_utc(month_w.end)


@given(day=dates, zone=zones)
def test_window_boundaries_are_at_local_midnight_or_first_valid_moment(
    day: date, zone: ZoneInfo
) -> None:
    window = day_window(day, zone)

    local_start = window.start.astimezone(zone)
    assert local_start.date() == day
    assert local_start.hour <= 1  # Havana skips 00:00 on its DST day
    assert window.start.tzinfo is not None


@pytest.mark.parametrize("naive", NAIVE_INSTANTS, ids=["no-tzinfo", "no-utcoffset"])
def test_time_window_contains_rejects_a_naive_instant(naive: datetime) -> None:
    window = day_window(NOW.date(), UTC)

    with pytest.raises(ValueError, match="timezone-aware"):
        window.contains(naive)


@pytest.mark.parametrize("build", [day_window, week_window, month_window])
def test_window_builders_reject_a_zone_without_a_utc_offset(
    build: Callable[[date, tzinfo], TimeWindow],
) -> None:
    with pytest.raises(ValueError, match="aware"):
        build(date(2026, 11, 7), OffsetlessTz())
