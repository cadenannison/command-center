"""Builders and strategies that parse through the real schema so fixtures cannot drift from it."""

from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from command_center.core.schema import Event

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
NAIVE = datetime(2026, 11, 7, 12, 0)  # noqa: DTZ001  (deliberately naive, for rejection tests)


class OffsetlessTz(tzinfo):
    """A tzinfo that reports no UTC offset, so datetimes carrying it are still naive."""

    def utcoffset(self, _dt: datetime | None, /) -> timedelta | None:
        return None

    def dst(self, _dt: datetime | None, /) -> timedelta | None:
        return None

    def tzname(self, _dt: datetime | None, /) -> str | None:
        return None


NAIVE_INSTANTS = [NAIVE, NAIVE.replace(tzinfo=OffsetlessTz())]


def make_event(**overrides: Any) -> Event:  # noqa: ANN401  (overrides are validated by pydantic)
    """Build a valid Event; keyword overrides replace the defaults."""
    fields: dict[str, Any] = {
        "id": "evt-1",
        "source": "canvas",
        "kind": "event",
        "title": "Title",
        "fetched_at": NOW,
    }
    fields.update(overrides)
    return Event.model_validate(fields)
