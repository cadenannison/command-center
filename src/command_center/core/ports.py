"""Ports the pure core depends on. Time, randomness and ids are passed in, never global."""

from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime
from typing import Literal, Protocol

from command_center.core.chat import ChatMessage
from command_center.core.geocode import GeocodeCandidate
from command_center.core.jobs import DeadLetter, DeadReport, Job, SyncReport
from command_center.core.ledger import ItemMark, LedgerEntry
from command_center.core.pairing import Device, RefreshRecord
from command_center.core.schema import Event, EventKind, SecretStatus, ValidationResult
from command_center.core.summary import DailySummary
from command_center.core.sync_state import SyncState
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


class IntegrationAdapter(Protocol):
    """A credential-only integration (an API key): it validates credentials and fetches nothing."""

    @property
    def name(self) -> str:
        """Stable name; it is the `source` under which its credentials are stored."""
        ...

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        """Check creds with a cheap call; raise the core.errors a SourceAdapter would."""
        ...


class Geocoder(Protocol):
    """Turns a city name into candidate places. Never logs or reports the query text."""

    async def search(self, query: str) -> list[GeocodeCandidate]:
        """Return up to MAX_CANDIDATES places for query, best match first; none found is [].

        Raises TransientError (unreachable, rate limited, 5xx) or FatalError (anything else).
        """
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


class ItemLedger(Protocol):
    """Item ledger: notes, check-offs, history and local tasks (decisions 0120, 0121).

    Events and the ledger share one database, so every write reads the item first.
    """

    def find(self, item_id: str, *, user_id: str = "local") -> Event | None:
        """Return the stored event with this id, synced or local, or None."""
        ...

    def marks(self, item_ids: Collection[str], *, user_id: str = "local") -> dict[str, ItemMark]:
        """Return the marks of those items that have a note or a check-off."""
        ...

    def check_off(self, item_id: str, at: datetime, *, user_id: str = "local") -> bool:
        """Mark the item done by the user, keeping the first time; False for an unknown item."""
        ...

    def undo(self, item_id: str, *, user_id: str = "local") -> bool:
        """Undo the user's check-off only (a source-done stays done); False when unknown."""
        ...

    def set_note(self, item_id: str, text: str, at: datetime, *, user_id: str = "local") -> bool:
        """Store text as the item's note; False for an unknown item."""
        ...

    def clear_note(self, item_id: str, *, user_id: str = "local") -> bool:
        """Remove the item's note; False when the item is unknown."""
        ...

    def history(self, window: TimeWindow, *, user_id: str = "local") -> list[LedgerEntry]:
        """Return entries whose done_at or gone_at is in [start, end), ordered by (at, item_id)."""
        ...

    def save_local(self, event: Event) -> None:
        """Insert or replace a local task; ValueError for an event that is not one."""
        ...

    def remove_local(self, item_id: str, *, user_id: str = "local") -> bool:
        """Delete a local task and its ledger row; False when there is none."""
        ...

    def delete_source(self, source: str, *, user_id: str = "local") -> int:
        """Delete the source's ledger rows, notes included, never `local`; returns the count."""
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


class ChatProvider(Protocol):
    """One AI backend that answers a chat. Read-only: it is given no tools."""

    @property
    def name(self) -> str:
        """Stable provider name, for example "ollama"."""
        ...

    async def complete(self, messages: Sequence[ChatMessage], system: str, max_tokens: int) -> str:
        """Return the assistant's reply to messages under system.

        Raises ChatRateLimited or ChatProviderError. Messages are user/assistant turns only; the
        system string is the only trusted text.
        """
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

    def delete(self, day: date, *, user_id: str = "local") -> None:
        """Drop the user's summary for day; a day with none stored is not an error."""
        ...


class AppSettingStore(Protocol):
    """Synchronous key-value store for small app settings, one value per (user, key)."""

    def get(self, key: str, *, user_id: str = "local") -> str | None:
        """Return the value stored under key, or None."""
        ...

    def set(self, key: str, value: str, *, user_id: str = "local") -> None:
        """Store value under key, replacing any existing value."""
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

    async def dead_letter(self, job: Job, reason: str) -> None:
        """Move job to the dead letters now, whatever its attempt (a failure retrying cannot fix).

        A job that is not in flight is a no-op, like ack and fail.
        """
        ...

    async def list_dead_letters(self) -> list[DeadLetter]:
        """Return the jobs that gave up, with reason and time."""
        ...


class ReportStream(Protocol):
    """At-least-once stream of SyncReports from the sync workers to the normalizer.

    One lane and one consumer group, like JobQueue. A report that is delivered and not acked is
    delivered again after the visibility timeout; one delivered too many times is dead-lettered.
    """

    async def publish(self, report: SyncReport) -> None:
        """Add report to the stream."""
        ...

    async def consume(self, group: str, consumer: str, block_ms: int) -> SyncReport | None:
        """Take the next report, waiting up to block_ms (0 = do not wait); None if none."""
        ...

    async def ack(self, report: SyncReport) -> None:
        """Mark report handled; one that is not in flight is a no-op."""
        ...

    async def dead_letter(self, report: SyncReport, reason: str) -> None:
        """Give up on report now (it can never be applied); not in flight is a no-op."""
        ...

    async def list_dead_reports(self) -> list[DeadReport]:
        """Return the reports that were given up on, with reason and time."""
        ...


class SyncStateStore(Protocol):
    """Synchronous persistence of each source's last sync state, shared between processes."""

    def put(self, state: SyncState, *, user_id: str = "local") -> None:
        """Store state as the source's current one, replacing any earlier state."""
        ...

    def get(self, source: str, *, user_id: str = "local") -> SyncState | None:
        """Return the source's stored state, or None."""
        ...

    def delete(self, source: str, *, user_id: str = "local") -> None:
        """Forget the source's state; none stored is not an error."""
        ...


class GenerationStore(Protocol):
    """Synchronous per-source counter, bumped when the source is disconnected (decision 0074).

    Work (a job, then its report) carries the generation current when it was queued; a result
    whose generation is below the current one belongs to a connection that no longer exists.
    """

    def current(self, source: str, *, user_id: str = "local") -> int:
        """The source's generation; 0 if it was never bumped."""
        ...

    def bump(self, source: str, *, user_id: str = "local") -> int:
        """Add one atomically and return the new generation; concurrent bumps never share one."""
        ...


ApplyOutcome = Literal["applied", "not_current", "older"]
"""What `ReportSink.apply` did: wrote, refused for its generation, or refused as older."""


class ReportSink(Protocol):
    """Writes a report's events and state together, only while its generation is current (0075).

    One synchronous port over the three tables a report touches, so an implementation can do the
    check and the writes in one transaction where its database allows it. Rows it writes carry the
    generation they were written under, which is what `purge_stale` compares.
    """

    def apply(
        self,
        generation: int,
        window: TimeWindow,
        events: Sequence[Event] | None,
        state: SyncState,
        *,
        user_id: str = "local",
    ) -> ApplyOutcome:
        """Apply one report for `state.source`, atomically.

        Reads the source's current generation and returns "not_current", writing nothing, unless
        it equals `generation`. Rows of the source written under an older generation (a purge
        that never finished) are deleted first. A `state.at` before the stored state's returns
        "older", writing nothing. Otherwise `EventStore.replace` semantics for `events` in
        `window` (None for a report that carries no events), the state is stored stamped with
        `generation`, and the result is "applied". An event of another user or source is a
        ValueError and nothing changes.
        """
        ...

    def purge_stale(self, source: str, *, user_id: str = "local") -> bool:
        """Delete the source's events and state written under a generation below the current one.

        The state row's generation says which one the source's events were written under, because
        `apply` writes both in one transaction. Rows written under the current generation are
        kept. Idempotent: nothing to delete is False, not an error. Returns whether anything was
        deleted.
        """
        ...


class TokenSource(Protocol):
    """Source of random tokens; the entropy lives outside core."""

    def new_token(self, num_bytes: int) -> str:
        """Return a fresh URL-safe random token carrying num_bytes of entropy."""
        ...


class DeviceStore(Protocol):
    """Synchronous persistence for pairing tokens and phone credentials.

    Only SHA-256 hashes (hex) are ever passed in.
    """

    def put_pairing(self, token_hash: str, expires_at: datetime, now: datetime) -> None:
        """Store a one-time pairing token.

        Also deletes expired pairing tokens and every other unused one, so at most one is live.
        """
        ...

    def take_pairing(self, token_hash: str, now: datetime) -> bool:
        """Atomically consume the token: True once if it exists and expires_at > now, else False."""
        ...

    def add_device(
        self, device: Device, refresh_hash: str, access_hash: str, access_expires_at: datetime
    ) -> None:
        """Store a new device with its first refresh and access credential hashes."""
        ...

    def rotate_refresh(
        self,
        old_refresh_hash: str,
        new_refresh_hash: str,
        new_access_hash: str,
        access_expires_at: datetime,
        now: datetime,
    ) -> str | None:
        """Atomically swap the credentials of the device whose current refresh hash this is.

        The old refresh hash is marked superseded, the new refresh and access hashes are stored
        (the device's older access hashes are dropped) and last_seen_at becomes now; returns the
        device id. If old_refresh_hash is unknown or already superseded, nothing changes and the
        result is None.
        """
        ...

    def refresh_record(self, refresh_hash: str) -> RefreshRecord | None:
        """Look up a refresh hash, current or superseded; None if unknown."""
        ...

    def device_for_access(self, access_hash: str, now: datetime) -> str | None:
        """Return the id of the device owning an unexpired access hash, else None."""
        ...

    def list_devices(self) -> list[Device]:
        """Return every paired device, oldest first."""
        ...

    def remove_device(self, device_id: str) -> bool:
        """Delete the device and every credential of it so its tokens stop working at once.

        Returns False if the device is unknown.
        """
        ...
