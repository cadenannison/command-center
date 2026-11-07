"""Ports the pure core depends on. Time, randomness and ids are passed in, never global."""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from command_center.core.schema import Event, EventKind, SecretStatus, ValidationResult
from command_center.core.windows import TimeWindow


class Clock(Protocol):
    """Source of the current time."""

    def now(self) -> datetime:
        """Return the current timezone-aware time."""
        ...


class Rng(Protocol):
    """Source of randomness."""

    def random(self) -> float:
        """Return a float in [0.0, 1.0)."""
        ...


class IdSource(Protocol):
    """Source of unique identifiers."""

    def new_id(self) -> str:
        """Return a new unique id."""
        ...


class SourceAdapter(Protocol):
    """One external source (Canvas, a calendar, email, weather). Raises core.errors on failure."""

    @property
    def name(self) -> str:
        """Stable source name, used as the `source` of every Event it returns."""
        ...

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        """Check creds; return refreshed creds in `updated_creds` when they changed."""
        ...

    async def fetch(self, creds: Mapping[str, str], window: TimeWindow) -> list[Event]:
        """Return the source's items for window, normalised to Event."""
        ...


class SecretStore(Protocol):
    """Write-only secret storage: one value per (user, source, key). Reads are for adapters only."""

    def set(self, source: str, key: str, value: str, *, user_id: str = "local") -> None:
        """Store or replace one key of the source's secret."""
        ...

    def get(self, source: str, *, user_id: str = "local") -> Mapping[str, str]:
        """Return every key of the source's secret; empty if none is stored."""
        ...

    def status(self, source: str, *, user_id: str = "local") -> Mapping[str, SecretStatus]:
        """Return per-key status (set, last4 if the value is 8+ characters); never a value."""
        ...

    def delete(self, source: str, *, user_id: str = "local") -> None:
        """Remove all keys of the source's secret; deleting when none is stored is not an error."""
        ...


class EventStore(Protocol):
    """Synchronous persistence for normalised events."""

    def upsert(self, events: Sequence[Event], *, user_id: str = "local") -> int:
        """Insert or replace events by (user_id, id); idempotent. Returns events written."""
        ...

    def query(
        self,
        window: TimeWindow,
        kinds: Collection[EventKind] | None = None,
        *,
        user_id: str = "local",
    ) -> list[Event]:
        """Return events in window (optionally only these kinds), ordered by time then id."""
        ...
