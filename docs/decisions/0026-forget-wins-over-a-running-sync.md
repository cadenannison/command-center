# 0026. A disconnect wins over a sync that is already running

Status: accepted

Context: With the sync running in the background (0025), `DELETE /v1/settings/{source}` can arrive while a sync is fetching. `disconnect` forgets the sync state but does not take the per-source lock, so the finishing sync wrote its result back and `GET /v1/settings` showed `keys: {}` with a sync result for a source the user had just disconnected.
Decision: `SyncService.forget` counts how often each source was forgotten. A sync notes the count after it marks `syncing`; when it finishes (or fails) and the count has changed, it drops the state it just wrote. The sync's own return value is unchanged. Events a running sync already fetched are still stored (stored events of a disconnected source stay by design, see `services.md`). A sync that only starts after the disconnect finds no credentials and reports `reconnect`, "Not connected": that is true and is not suppressed.
Alternative: Make `disconnect` take the source lock, so it waits for the running sync. Rejected: a disconnect would block behind retries of up to 7 seconds. Documenting the race as accepted was also rejected: the screen would contradict the user's last action.
Reason: Small, local to the service, in memory like the state it protects, and testable with a gated fake adapter.
Where: `src/command_center/services/sync.py` (`forget`, `sync`); `docs/contracts/services.md`.
Revisit when: Sync state is persisted or shared across processes (distributed workers); a counter in one process then no longer covers it.
