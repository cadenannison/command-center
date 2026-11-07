# Contract: services

Application logic. Depends on core ports only; never an adapter, storage or framework. Every store call (`EventStore`, `SecretStore`) runs through `asyncio.to_thread` (decision 0016). Decisions: 0019-0026, 0028, 0029.

## Public exports (module: names)
- `sync`: `SyncService`, `MAX_RETRIES`, `STORE_UNAVAILABLE_MESSAGE`, `UNEXPECTED_MESSAGE`.
- `agenda`: `AgendaService`, `ATTENTION_URGENCY`.
- `settings`: `SettingsService`.
- `models`: `SyncState`, `SourceSettings`, `ConnectResult`, `SyncStatus`.
- `errors`: `UnknownSourceError`, `describe`.
- `horizon`: `horizon_window`.
- `container`: `Container(sync, agenda, settings)`, the set the api serves.

## Behaviour
### SyncService(adapters, secrets, events, clock, *, sleep=asyncio.sleep)
- `sync(source) -> SyncState` and `sync_all() -> list[SyncState]` (concurrent; one source's failure does not touch the others). An unknown source raises `UnknownSourceError`. Source failures are returned as state, never raised.
- Window: `horizon_window(clock.now() in UTC)`: midnight 14 days before today to midnight 60 days after it. The fetch gets the credentials from `secrets.get(source)`; after a fully successful fetch the result goes to `events.replace(source, window, events)`, which deletes the source's stored events in that window that the fetch no longer returns (removed or moved at the source) and upserts the rest, in one transaction. Any failure (`reconnect`, `error`, no credentials) leaves the stored events as they were; events outside the window are never pruned (decision 0028).
- Result per source, kept in memory (lost on restart): `SyncState(source, status, message, at)` with `status` `syncing | ok | reconnect | error`.
  - `syncing`: set at the start of `sync()` (and by `mark_syncing`), "Sync in progress"; always replaced by one of the three below.
  - `ok`: "Synced N items" (N is the number of events `replace` wrote).
  - no stored credentials: `reconnect`, "Not connected"; the adapter is not called.
  - `AuthExpired`: `reconnect`; not retried.
  - `TransientError`: up to 3 retries (4 fetches), sleeping 1, 2, 4 seconds; each retry is logged with source, attempt, delay and reason; then `error` with the reason.
  - `FatalError`: `error` with the reason; not retried.
  - `core.errors.SecretStoreError`: `error`, message exactly `secret store unavailable`.
- Each retry and give-up is logged with the source, attempt, delay and reason in the message text (and as `extra` fields).
- Messages carry the adapter's own error text (truncated to 200 characters); adapters must keep credentials out of it (`docs/contracts/adapters.md` rule 6).
- Syncs of one source are serialised. `state(source)`, `forget(source)`, `record_error(source, message)`, `sources()`.
- Any other exception (a bug, a database failure) propagates, but first sets the state `error` "Sync failed unexpectedly" so the source is never left `syncing`.
- `forget(source)` while a sync of that source runs: the running sync finishes but does not remember its result, so a disconnect is not undone (decision 0026). That sync also calls `events.delete_source(source)` after its write, so its events do not outlive the disconnect (decision 0029).
- `purge(source)` (async): `forget(source)`, then `events.delete_source(source)` on a worker thread. `SettingsService.disconnect` calls it.
- `mark_syncing(source) -> SyncState`: records `syncing` without fetching; unknown source is `UnknownSourceError`.

### AgendaService(events, clock, tz)
- `day(date)`, `week(date)` (Monday start), `month(date)`, `between(window)`: events in the window, in `tz`, **re-scored** with `core.scoring.urgency(event, clock.now().astimezone(tz))` (the stored urgency is ignored), ordered by `start` (else `due`) then id.
- `attention()`: events in the horizon window around today whose rescored urgency is 70 or more, or that are emails with status `owed` or `overdue`; ordered by urgency descending, then time. An assignment overdue by more than 14 days is outside the horizon and is not listed.

### SettingsService(adapters, secrets, sync)
- `connect(source, creds) -> ConnectResult`: `adapter.validate(creds)`. If `ok`, stores each field of `{**creds, **updated_creds}` with `secrets.set` (keys not mentioned stay), then marks the source `syncing` and returns that state. It does not sync: the caller runs `SyncService.sync(source)` afterwards (decision 0025). If not `ok`, or `validate` raises `AuthExpired`/`TransientError`/`FatalError`, returns `ok=false` with a message and stores nothing. A store failure returns `ok=false`, message `secret store unavailable`, and an error state; keys written before the failure stay stored (there is no per-key rollback). Unknown source: `UnknownSourceError`.
- `status() -> list[SourceSettings]`: per registered source, per key `{set, last4}` (core `SecretStatus`) plus its `SyncState` or None. Never a value. If the store is unavailable the entry has no keys and an error state, which is reported but does not replace the remembered sync result.
- `disconnect(source) -> SourceSettings`: deletes every key, then `SyncService.purge(source)`: forgets the sync state and deletes every stored event of the source, dated or not (decision 0029). If the secret store is unavailable it returns the error state and neither forgets nor deletes. Unknown source: `UnknownSourceError`.

### Secret store errors
Services catch `core.errors.SecretStoreError` (decision 0024) and report only the fixed text `secret store unavailable`; the error's own message is never copied into a state, result or log line.

## Not built yet
- Summary orchestration: runs redaction, then the chosen provider, only when the user has opted in.
- Scheduled sync (`Settings.sync_interval_minutes` is not used yet; workers will call `sync_all`).
- Pairing: issues and checks short-lived tokens.
