# 0408. Sync and views share one local-day window

Status: accepted

Context: `SyncService` and `SyncEnqueuer` built the sync window from UTC now (`horizon_window(now.astimezone(UTC))`), while `AgendaService.attention` builds it from local now. The two windows differ by the UTC offset at both edges, so near local midnight the sync could fetch and replace a different span than the agenda shows (audit R08, Q04; card 03).
Decision: both take a keyword-only `zone: ZoneInfo` and build the window from `clock.now().astimezone(zone)` with the same `horizon_window` the views use. The default is UTC, documented "tests and tools only; production roots must pass the configured zone". `app.py` (`build_container`, and `build_queued_sync` through a required keyword `tz`) and `workers/__main__.py` (`_run_scheduler`) pass `ZoneInfo(settings.tz)`. The `diagnose learningsuite` command also builds its window in the configured zone, so "inside the window" matches a sync. `QueuedSyncService` builds no window and is unchanged.
Alternative: a required `zone` argument. Rejected: 40 `SyncService(...)` calls in 31 test files and 11 `SyncEnqueuer(...)` calls in 4 test files would each need a one-line edit, and the existing tests must not change.
Accepted risk: a future caller may forget the zone and silently get UTC windows. The guard is behavioural: `tests/test_sync_window_local.py` builds the single-process container, the distributed container and the scheduler worker with a configured zone other than UTC and asserts the sync service and the enqueuer carry it, and that the window near local midnight and across a DST change differs from the UTC-date window.
Consequences: constructor signatures in the services contract change; a zone change takes effect at the next sync; jobs already queued keep the window they were published with.
Where: `services/sync.py`, `services/scheduler.py`, `app.py`, `workers/__main__.py`. Tests: `tests/test_sync_window_local.py`.
Revisit when: the existing tests are next edited under a `tests: modify` card (then make `zone` required), or a new composition root appears.
