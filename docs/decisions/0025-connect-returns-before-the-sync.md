# 0025. Connecting returns before the sync; a source can be "syncing"

Status: accepted

Context: `PUT /v1/settings/{source}` validated, stored and then waited for a full sync with retries (up to 7 seconds of backoff plus fetch time), so the request could hang behind a slow source.
Decision: `SettingsService.connect` validates and stores, then calls `SyncService.mark_syncing` and returns a `ConnectResult` whose `sync` is the `syncing` state. The PUT handler schedules `SyncService.sync(source)` as a FastAPI background task, only when `ok` is true. `SyncService.sync` itself sets `syncing` at its start and ends in `ok`, `reconnect` or `error`. An unexpected exception inside a sync sets `error` ("Sync failed unexpectedly") and is re-raised, so a bug cannot leave the source `syncing`. `GET /v1/settings` shows the state. The state stays in memory, as before.
Alternative: Return only after the sync (the old behaviour), or start the sync from the service with `asyncio.create_task`. The first blocks the caller; the second needs the service to own task lifetimes and keep references so tasks are not collected.
Reason: Background tasks are the framework's own mechanism, run after the response, and keep the service free of task bookkeeping. Marking before returning makes the first `GET` after `PUT` deterministic.
Where: `src/command_center/services/sync.py`, `settings.py`, `models.py`; `src/command_center/api/settings.py`; `docs/contracts/services.md`, `api.md`; `docs/generated/`.
Revisit when: Workers run syncs (then the state needs to be shared across processes) or a client needs progress beyond the status.
