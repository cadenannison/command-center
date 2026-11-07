"""The real Clock, for composition roots and adapters."""

from datetime import UTC, datetime


class SystemClock:
    """Clock backed by the host's wall clock, always in UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)
