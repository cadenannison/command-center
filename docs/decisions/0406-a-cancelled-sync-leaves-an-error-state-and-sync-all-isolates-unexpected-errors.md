# 0406. A cancelled sync leaves an error state, and sync_all isolates unexpected errors

Status: accepted

Context: cancelling `SyncService.sync` (shutdown, scheduler stop) left the source persisted as "syncing" for ever, because only `except Exception` reset it. In `sync_all`, one adapter raising an unexpected error made `gather` raise and lose every other source's result, against the docstring.
Decision: `sync()` writes an `error` state with the fixed text "Sync was interrupted" on `asyncio.CancelledError`, then re-raises the cancellation unchanged (a failure of the reset itself is logged, never replaces the cancellation). `sync_all()` wraps each source so an unexpected error becomes that source's error state (fixed text "Sync failed unexpectedly", logged by exception class only); a cancelled `sync_all` still propagates.
Alternative: a new "interrupted" status (rejected: it changes the SyncStatus values the API and UI share); resetting in a `finally` for every non-success exit (rejected: it would also overwrite the reconnect and error states a normal sync returns).
Reason: an interrupted source should read as interrupted and be retried next cycle, and one bad adapter must not hide the others.
Consequences: a source shows "error: Sync was interrupted" until the next sync. No interface change; `queued_sync.py` not changed (it only enqueues and never sets a state that outlives its work).
Where: `services/sync.py` (`sync`, `sync_all`, `_sync_isolated`). Tests: `tests/test_sync_failure_modes.py`.
Revisit when: retry and backoff are reworked (audit R17), or an "interrupted" status is wanted in the UI.
