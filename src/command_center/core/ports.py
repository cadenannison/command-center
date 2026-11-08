"""Ports the pure core depends on. Time, randomness and ids are passed in, never global."""

from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime
from typing import Protocol

from command_center.core.jobs import DeadLetter, Job
from command_center.core.schema import Event, EventKind, SecretStatus, ValidationResult
from command_center.core.summary import DailySummary
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

    def replace(
        self,
        source: str,
        window: TimeWindow,
        events: Sequence[Event],
        *,
        user_id: str = "local",
    ) -> int:
        """Atomically swap a source's events in window for events; call only after a full fetch.

        In one transaction, delete the user's events of source that match window under the
        same rules as query (undated events never match, so are never deleted), then upsert
        events. On failure the old events remain; stored events outside window are kept.
        Every stored event of source in window missing from events is deleted, so never pass
        a partial result. An event whose user_id or source differs is a ValueError and nothing
        changes. Returns the number of distinct events written.
        """
        ...

    def delete_source(self, source: str, *, user_id: str = "local") -> int:
        """Delete every event of source for the user, dated or undated; returns the count."""
        ...


class SummaryProvider(Protocol):
    """One AI backend that turns a redacted prompt into a DailySummary."""

    @property
    def name(self) -> str:
        """Stable provider name, for example "gemini"."""
        ...

    async def summarize(self, prompt: str) -> DailySummary:
        """Return the summary for prompt; raises SummaryRateLimited or SummaryProviderError."""
        ...


class SummaryStore(Protocol):
    """Synchronous persistence for one DailySummary per (user, day)."""

    def get(self, day: date, *, user_id: str = "local") -> DailySummary | None:
        """Return the summary stored for day, or None."""
        ...

    def put(self, day: date, summary: DailySummary, *, user_id: str = "local") -> None:
        """Store summary for day, replacing any existing row for that user and day."""
        ...

    def latest_before(self, day: date, *, user_id: str = "local") -> DailySummary | None:
        """Return the summary of the user's latest stored day strictly before day, or None."""
        ...


class JobQueue(Protocol):
    """At-least-once queue of Jobs, shared by the scheduler and the workers."""

    async def publish(self, job: Job) -> None:
        """Add job to the queue."""
        ...

    async def consume(self, group: str, consumer: str, block_ms: int) -> Job | None:
        """Take the next ready job, waiting up to block_ms (0 = do not wait); None if none.

        A job that is not acked is redelivered after the visibility timeout with attempt + 1.
        """
        ...

    async def ack(self, job: Job) -> None:
        """Mark job done; a job that is not in flight is a no-op."""
        ...

    async def fail(self, job: Job, reason: str) -> None:
        """Requeue job as attempt + 1 after RetryPolicy.delay, or dead-letter it when exhausted.

        Dead-lettering applies when RetryPolicy.exhausted(job.attempt); a job that is not in
        flight is a no-op.
        """
        ...

    async def list_dead_letters(self) -> list[DeadLetter]:
        """Return the jobs that gave up, with reason and time."""
        ...
