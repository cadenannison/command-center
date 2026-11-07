# 0029. A disconnect deletes the source's events; a late sync cleans up after itself

Status: accepted. Supersedes the clause of 0026 that says events a running sync already fetched are still stored.

Context: With `delete_source` available (0028), keeping a disconnected source's events would leave its titles in the agenda with no way to refresh or remove them. A sync running during the disconnect could also write its events after the delete.
Decision: `SettingsService.disconnect` calls `SyncService.purge(source)` once the secrets are deleted. `purge` calls `forget` first and then `EventStore.delete_source`. A sync that finds the source was forgotten while it ran (the counter of 0026) drops its state and calls `delete_source` itself after its write. If the secret store fails, nothing is forgotten or deleted. `SettingsService` reaches the event store through `SyncService`, which already owns that port, so its constructor is unchanged.
Alternative: (a) Give `SettingsService` the `EventStore` and call `delete_source` directly, as the task card words it: changes its constructor and every caller, and the forget-then-delete order would live in two classes. (b) Take the source lock in `disconnect`: rejected in 0026 (blocks behind retries). (c) Keep the events: leaves data of a source the user removed.
Reason: Forget-then-delete in `disconnect` and delete-after-write in a forgotten sync cover both orders of the race: either the sync's write comes before the disconnect's delete, or the sync sees the forget and deletes after its own write. The counter is already there.
Consequence for clients: `DELETE /v1/settings/{source}` now also removes the source's events. Paths and schemas are unchanged, but this is a visible behaviour change of a /v1 route; only its description in `docs/generated/openapi.json` changes.
Where: `src/command_center/services/sync.py` (`purge`, `_discard_if_forgotten`), `src/command_center/services/settings.py` (`disconnect`); `docs/contracts/services.md`.
Revisit when: Sync state is shared across processes (0026's condition); the counter then no longer sees a forget from another process.
