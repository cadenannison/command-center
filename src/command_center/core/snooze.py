"""Snooze presets, worked out in the user's local day (decision 0399). Pure: now comes in."""

from datetime import datetime, time, timedelta, tzinfo
from typing import Literal

SnoozePreset = Literal["later_today", "tomorrow_morning", "next_week"]

MORNING = time(8, 0)
LATER_TODAY_HOURS = 3
_MONDAY = 0
_DAYS_PER_WEEK = 7


def snooze_until(preset: SnoozePreset, now: datetime, tz: tzinfo) -> datetime:
    """The instant the snooze ends, always after `now`.

    later_today: three hours on, or 23:59 if that would pass local midnight (the start of
    tomorrow when under a minute is left). tomorrow_morning: 08:00 local tomorrow. next_week:
    08:00 local on the next Monday (a week on when today is Monday).
    """
    if now.utcoffset() is None:
        msg = "a timezone-aware now is required"
        raise ValueError(msg)
    local = now.astimezone(tz)
    tomorrow = local.date() + timedelta(days=1)
    midnight = datetime.combine(tomorrow, time.min, tzinfo=tz)
    if preset == "later_today":
        candidate = (now + timedelta(hours=LATER_TODAY_HOURS)).astimezone(tz)  # elapsed, not wall
        if candidate.date() == local.date():
            return candidate
        evening = midnight - timedelta(minutes=1)
        return evening if evening > local else midnight
    if preset == "tomorrow_morning":
        return datetime.combine(tomorrow, MORNING, tzinfo=tz)
    days = (_MONDAY - local.weekday()) % _DAYS_PER_WEEK or _DAYS_PER_WEEK
    return datetime.combine(local.date() + timedelta(days=days), MORNING, tzinfo=tz)
