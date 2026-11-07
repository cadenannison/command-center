"""The shared in-memory fakes for core ports. Behaviour mirrors docs/contracts/core.md."""

from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime, timedelta

from command_center.core.schema import Event, EventKind, SecretStatus, secret_status
from command_center.core.windows import TimeWindow


class FakeClock:
    """A Clock that only moves when the test says so."""

    def __init__(self, now: datetime) -> None:
        self._now = self._checked(now)

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = self._checked(now)

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    @staticmethod
    def _checked(now: datetime) -> datetime:
        if now.utcoffset() is None:
            msg = "FakeClock needs a timezone-aware datetime"
            raise ValueError(msg)
        return now


class InMemorySecretStore:
    """SecretStore backed by a dict keyed by (user_id, source) holding key -> value."""

    def __init__(self) -> None:
        self._secrets: dict[tuple[str, str], dict[str, str]] = {}

    def set(self, source: str, key: str, value: str, *, user_id: str = "local") -> None:
        self._secrets.setdefault((user_id, source), {})[key] = value

    def get(self, source: str, *, user_id: str = "local") -> Mapping[str, str]:
        return dict(self._secrets.get((user_id, source), {}))

    def status(self, source: str, *, user_id: str = "local") -> Mapping[str, SecretStatus]:
        return {
            key: secret_status(value)
            for key, value in self._secrets.get((user_id, source), {}).items()
        }

    def delete(self, source: str, *, user_id: str = "local") -> None:
        self._secrets.pop((user_id, source), None)


class InMemoryEventStore:
    """EventStore backed by a dict keyed by (user_id, id)."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], Event] = {}

    def upsert(self, events: Sequence[Event], *, user_id: str = "local") -> int:
        for event in events:
            if event.user_id != user_id:
                msg = f"Event {event.id} has user_id {event.user_id!r}, expected {user_id!r}"
                raise ValueError(msg)
        written = {event.id: event for event in events}
        for event_key, event in written.items():
            self._events[(user_id, event_key)] = event
        return len(written)

    def query(
        self,
        window: TimeWindow,
        kinds: Collection[EventKind] | None = None,
        *,
        user_id: str = "local",
    ) -> list[Event]:
        hits = [
            event
            for (owner, _), event in self._events.items()
            if owner == user_id
            and (kinds is None or event.kind in kinds)
            and _anchor(event) is not None
            and _overlaps(event, window)
        ]
        return sorted(hits, key=lambda e: (_anchor_utc(e), e.id))


def _anchor(event: Event) -> datetime | None:
    return event.start if event.start is not None else event.due


def _anchor_utc(event: Event) -> datetime:
    anchor = _anchor(event)
    assert anchor is not None
    return anchor.astimezone(UTC)


def _overlaps(event: Event, window: TimeWindow) -> bool:
    start = _anchor_utc(event)
    if event.end is not None and event.end.astimezone(UTC) > start:
        return start < window.end.astimezone(UTC) and event.end.astimezone(
            UTC
        ) > window.start.astimezone(UTC)
    return window.contains(start)
