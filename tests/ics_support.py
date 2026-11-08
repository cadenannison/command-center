"""Helpers for the iCalendar tests: fixture loading, a fixed zone and window."""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from command_center.core.windows import TimeWindow

DENVER = ZoneInfo("America/Denver")
FIXTURES = Path(__file__).parent / "fixtures" / "ics"
# Local midnights: Oct 31 (MDT) to Nov 15 (MST), across the 2026-11-01 DST change.
WINDOW = TimeWindow(
    start=datetime(2026, 10, 31, tzinfo=DENVER), end=datetime(2026, 11, 15, tzinfo=DENVER)
)


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)
