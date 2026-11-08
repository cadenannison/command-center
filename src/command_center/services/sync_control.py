"""What the settings service, the routes and the scheduler need from "the sync" (decision 0074).

`SyncService` runs syncs in this process (single mode). `QueuedSyncService` queues them for the
workers and reads what the normalizer recorded (distributed mode). Both satisfy this.
"""

from typing import Protocol

from command_center.core.sync_state import SyncState


class SyncControl(Protocol):
    """Start syncs, report their state, and clean up after a disconnect."""

    def sources(self) -> list[str]:
        """Names of every registered source."""
        ...

    def state(self, source: str) -> SyncState | None:
        """The source's last recorded sync state, or None if it has none."""
        ...

    def mark_syncing(self, source: str) -> SyncState:
        """The "syncing" state to show right after a connect; UnknownSourceError if not a source."""
        ...

    def record_error(self, source: str, message: str) -> SyncState:
        """An error state that did not come from a sync attempt."""
        ...

    def error_state(self, source: str, message: str) -> SyncState:
        """An error state for source, to report without replacing its last sync result."""
        ...

    async def sync(self, source: str) -> SyncState:
        """Start a sync of one source; failures are reported in the state, never raised."""
        ...

    async def sync_all(self) -> list[SyncState]:
        """Start a sync of every source."""
        ...

    async def purge(self, source: str) -> None:
        """After a disconnect: delete the source's events and sync state, and cancel its work."""
        ...
