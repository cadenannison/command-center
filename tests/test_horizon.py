"""The sync/attention horizon: 14 days back to 60 days ahead, from local midnights."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from builders import NAIVE, NOW
from command_center.services.horizon import horizon_window

DENVER = ZoneInfo("America/Denver")


def test_horizon_spans_14_days_before_to_60_days_after_today() -> None:
    window = horizon_window(NOW)

    assert window.start == datetime(2026, 10, 24, tzinfo=UTC)
    assert window.end == datetime(2027, 1, 6, tzinfo=UTC)


def test_horizon_edges_are_local_midnights_of_the_zone_of_now() -> None:
    window = horizon_window(NOW.astimezone(DENVER))  # 05:00 on 2026-11-07 in Denver

    assert window.start == datetime(2026, 10, 24, 6, 0, tzinfo=UTC)  # MDT, UTC-6
    assert window.end == datetime(2027, 1, 6, 7, 0, tzinfo=UTC)  # MST, UTC-7


def test_horizon_takes_today_from_the_zone_of_now() -> None:
    late_utc = datetime(2026, 11, 8, 3, 0, tzinfo=UTC)  # still Nov 7 in Denver

    assert horizon_window(late_utc.astimezone(DENVER)).start.date() == datetime(2026, 10, 24).date()  # noqa: DTZ001


def test_horizon_rejects_a_naive_now() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        horizon_window(NAIVE)
