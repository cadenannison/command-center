"""Day, week and month windows in the user's timezone, built from local midnight (DST-safe)."""

from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator


class TimeWindow(BaseModel):
    """Half-open interval [start, end) between two timezone-aware instants."""

    model_config = ConfigDict(frozen=True)

    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        # Compare as UTC: same-tzinfo datetimes otherwise compare by wall clock (wrong across DST).
        if self.end.astimezone(UTC) <= self.start.astimezone(UTC):
            msg = "TimeWindow end must be after start"
            raise ValueError(msg)
        return self

    def contains(self, instant: datetime) -> bool:
        """Return True if instant is in [start, end); a naive instant is a ValueError."""
        if instant.utcoffset() is None:
            msg = "TimeWindow.contains needs a timezone-aware instant"
            raise ValueError(msg)
        moment = instant.astimezone(UTC)
        return self.start.astimezone(UTC) <= moment < self.end.astimezone(UTC)


def _midnight(day: date, zone: tzinfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone)


def day_window(day: date, zone: tzinfo) -> TimeWindow:
    """Local midnight of day to local midnight of the next day."""
    return TimeWindow(start=_midnight(day, zone), end=_midnight(day + timedelta(days=1), zone))


def week_window(day: date, zone: tzinfo) -> TimeWindow:
    """The Monday-to-Monday week containing day."""
    monday = day - timedelta(days=day.weekday())
    return TimeWindow(
        start=_midnight(monday, zone), end=_midnight(monday + timedelta(days=7), zone)
    )


def month_window(day: date, zone: tzinfo) -> TimeWindow:
    """The first of day's month to the first of the next month."""
    first = day.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)  # 32 days always lands next month
    return TimeWindow(start=_midnight(first, zone), end=_midnight(following, zone))
