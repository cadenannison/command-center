"""The shared in-memory fakes for core ports. Behaviour mirrors docs/contracts/core.md."""

from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta

from command_center.core.schema import Event, EventKind, SecretStatus, secret_status
from command_center.core.summary import DailySummary
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

    def replace(
        self,
        source: str,
        window: TimeWindow,
        events: Sequence[Event],
        *,
        user_id: str = "local",
    ) -> int:
        for event in events:
            if event.user_id != user_id:
                msg = f"Event {event.id} has user_id {event.user_id!r}, expected {user_id!r}"
                raise ValueError(msg)
            if event.source != source:
                msg = f"Event {event.id} has source {event.source!r}, expected {source!r}"
                raise ValueError(msg)
        stale = [
            key
            for key, event in self._events.items()
            if key[0] == user_id
            and event.source == source
            and _anchor(event) is not None
            and _overlaps(event, window)
        ]
        for key in stale:
            del self._events[key]
        # Through upsert, so subclasses that observe upsert calls also see a replace.
        return self.upsert(events, user_id=user_id)

    def delete_source(self, source: str, *, user_id: str = "local") -> int:
        doomed = [
            key
            for key, event in self._events.items()
            if key[0] == user_id and event.source == source
        ]
        for key in doomed:
            del self._events[key]
        return len(doomed)

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


class InMemorySummaryStore:
    """SummaryStore backed by a dict keyed by (user_id, day)."""

    def __init__(self) -> None:
        self._summaries: dict[tuple[str, date], DailySummary] = {}

    def get(self, day: date, *, user_id: str = "local") -> DailySummary | None:
        return self._summaries.get((user_id, day))

    def put(self, day: date, summary: DailySummary, *, user_id: str = "local") -> None:
        self._summaries[(user_id, day)] = summary

    def delete(self, day: date, *, user_id: str = "local") -> None:
        self._summaries.pop((user_id, day), None)

    def latest_before(self, day: date, *, user_id: str = "local") -> DailySummary | None:
        days = [stored for owner, stored in self._summaries if owner == user_id and stored < day]
        return self._summaries[(user_id, max(days))] if days else None


class FakeSummaryProvider:
    """SummaryProvider that returns a canned summary or raises a canned error; records prompts."""

    name = "fake"

    def __init__(self, outcome: DailySummary | Exception) -> None:
        self._outcome = outcome
        self.prompts: list[str] = []
        self.calls = 0

    async def summarize(self, prompt: str) -> DailySummary:
        self.calls += 1
        self.prompts.append(prompt)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class InMemoryAppSettingStore:
    """AppSettingStore backed by a dict keyed by (user_id, key)."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], str] = {}

    def get(self, key: str, *, user_id: str = "local") -> str | None:
        return self._values.get((user_id, key))

    def set(self, key: str, value: str, *, user_id: str = "local") -> None:
        self._values[(user_id, key)] = value
