"""Snooze presets in the user's local day, around midnight and across DST (decision 0399)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from command_center.core.snooze import snooze_until

DENVER = ZoneInfo("America/Denver")


def local(y: int, m: int, d: int, hh: int, mm: int = 0, ss: int = 0) -> datetime:  # noqa: PLR0913, PLR0917
    return datetime(y, m, d, hh, mm, ss, tzinfo=DENVER)


def test_later_today_is_three_hours_on_when_that_is_still_today() -> None:
    assert snooze_until("later_today", local(2026, 11, 9, 10), DENVER) == local(2026, 11, 9, 13)


def test_later_today_stops_at_23_59_instead_of_crossing_midnight() -> None:
    assert snooze_until("later_today", local(2026, 11, 9, 22), DENVER) == local(2026, 11, 9, 23, 59)


def test_later_today_in_the_last_minute_falls_to_the_start_of_tomorrow() -> None:
    now = local(2026, 11, 9, 23, 59, 30)
    assert snooze_until("later_today", now, DENVER) == local(2026, 11, 10, 0)


def test_the_local_day_not_the_utc_day_decides_what_today_is() -> None:
    now = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)  # 20:00 on Nov 9 in Denver
    assert snooze_until("tomorrow_morning", now, DENVER) == local(2026, 11, 10, 8)


def test_tomorrow_morning_just_after_local_midnight_is_that_same_morning_next_day() -> None:
    assert snooze_until("tomorrow_morning", local(2026, 11, 10, 0, 1), DENVER) == local(
        2026, 11, 11, 8
    )


def test_tomorrow_morning_just_before_local_midnight_is_the_next_morning() -> None:
    assert snooze_until("tomorrow_morning", local(2026, 11, 9, 23, 59), DENVER) == local(
        2026, 11, 10, 8
    )


@pytest.mark.parametrize(
    ("now", "expected_day"),
    [(local(2026, 11, 9, 9), 16), (local(2026, 11, 12, 9), 16), (local(2026, 11, 15, 23, 59), 16)],
)
def test_next_week_is_the_next_monday_morning_and_a_monday_means_a_week_on(
    now: datetime, expected_day: int
) -> None:
    assert snooze_until("next_week", now, DENVER) == local(2026, 11, expected_day, 8)


def test_tomorrow_morning_across_the_fall_back_change_is_still_08_00_local() -> None:
    # Clocks go back on 2026-11-01 in Denver; the morning after is MST, 15:00Z.
    result = snooze_until("tomorrow_morning", local(2026, 10, 31, 20), DENVER)
    assert result.astimezone(UTC) == datetime(2026, 11, 1, 15, 0, tzinfo=UTC)


def test_later_today_counts_elapsed_hours_across_the_fall_back_change() -> None:
    now = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)  # 00:30 MDT on the 25-hour day
    assert snooze_until("later_today", now, DENVER).astimezone(UTC) == datetime(
        2026, 11, 1, 9, 30, tzinfo=UTC
    )


def test_a_naive_now_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        snooze_until("later_today", datetime(2026, 11, 9, 10), DENVER)  # noqa: DTZ001


def test_later_today_on_the_spring_forward_day_counts_elapsed_hours_across_the_gap() -> None:
    now = datetime(2026, 3, 8, 8, 30, tzinfo=UTC)  # 01:30 MST, an hour before the clocks jump
    result = snooze_until("later_today", now, DENVER)

    assert result.astimezone(UTC) == datetime(2026, 3, 8, 11, 30, tzinfo=UTC)
    assert result.astimezone(DENVER) == local(2026, 3, 8, 5, 30)


def test_tomorrow_morning_the_evening_before_spring_forward_is_08_00_daylight_time() -> None:
    result = snooze_until("tomorrow_morning", local(2026, 3, 7, 21), DENVER)

    assert result.astimezone(UTC) == datetime(2026, 3, 8, 14, 0, tzinfo=UTC)  # 08:00 MDT


def test_tomorrow_morning_on_the_spring_forward_day_is_08_00_daylight_time() -> None:
    result = snooze_until("tomorrow_morning", local(2026, 3, 8, 12), DENVER)

    assert result.astimezone(UTC) == datetime(2026, 3, 9, 14, 0, tzinfo=UTC)


def test_next_week_across_the_spring_forward_change_is_08_00_on_the_new_offset() -> None:
    result = snooze_until("next_week", local(2026, 3, 2, 9), DENVER)  # a Monday, still MST

    assert result.astimezone(UTC) == datetime(2026, 3, 9, 14, 0, tzinfo=UTC)  # 08:00 MDT


def test_later_today_on_the_fall_back_day_stops_before_that_days_midnight() -> None:
    now = local(2026, 11, 1, 22)  # MST, after the clocks went back

    assert snooze_until("later_today", now, DENVER) == local(2026, 11, 1, 23, 59)


def test_tomorrow_morning_on_the_fall_back_day_is_08_00_standard_time() -> None:
    result = snooze_until("tomorrow_morning", local(2026, 11, 1, 12), DENVER)

    assert result.astimezone(UTC) == datetime(2026, 11, 2, 15, 0, tzinfo=UTC)


def test_next_week_across_the_fall_back_change_is_08_00_on_the_new_offset() -> None:
    result = snooze_until("next_week", local(2026, 10, 26, 9), DENVER)  # a Monday, still MDT

    assert result.astimezone(UTC) == datetime(2026, 11, 2, 15, 0, tzinfo=UTC)  # 08:00 MST
