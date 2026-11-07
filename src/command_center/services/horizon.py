"""The span of time the app syncs and watches for attention items."""

from datetime import datetime, time, timedelta

from command_center.core.windows import TimeWindow

DAYS_BEHIND = 14
DAYS_AHEAD = 60


def horizon_window(now: datetime) -> TimeWindow:
    """Local midnight 14 days before today to local midnight 60 days after it, in now's zone.

    `now` must be timezone-aware; its tzinfo defines "today" and the midnights.
    """
    if now.utcoffset() is None:
        msg = "horizon_window needs a timezone-aware now"
        raise ValueError(msg)
    today = now.date()
    return TimeWindow(
        start=datetime.combine(today - timedelta(days=DAYS_BEHIND), time.min, tzinfo=now.tzinfo),
        end=datetime.combine(today + timedelta(days=DAYS_AHEAD), time.min, tzinfo=now.tzinfo),
    )
