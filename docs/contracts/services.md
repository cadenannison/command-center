# Contract: services

Application logic. Depends on core ports only; never an adapter, storage or framework. Every store call (`EventStore`, `SecretStore`) runs through `asyncio.to_thread` (decision 0016). Decisions: 0019-0026, 0028, 0029, 0034, 0035, 0052, 0053, 0056, 0058, 0070, 0071, 0074.

## Public exports (module: names)
- `sync`: `SyncService`, `MAX_RETRIES`, `STORE_UNAVAILABLE_MESSAGE`, `UNEXPECTED_MESSAGE`.
- `sync_control`: `SyncControl` (Protocol: what the settings service, routes and scheduler need from "the sync"; `SyncService` and `QueuedSyncService` both satisfy it).
- `queued_sync`: `QueuedSyncService`, `SYNCING_MESSAGE`, `QUEUE_FAILED_MESSAGE` (the api's sync in distributed mode).
- `agenda`: `AgendaService`, `ATTENTION_URGENCY`.
- `settings`: `SettingsService`.
- `models`: `SyncState`, `SourceSettings`, `ConnectResult`, `SyncStatus` (`SyncState` and `SyncStatus` are defined in `core.sync_state` and re-exported).
- `errors`: `UnknownSourceError`, `describe` (bounded, for log lines), `error_text` (uncut, the input of a display message), `safe_message`.
- `horizon`: `horizon_window`.
- `summary`: `SummaryService`, `SummaryResult`, `PROVIDER_STORED`, `PROVIDER_TEMPLATE`.
- `scheduler`: `SyncScheduler`, `SyncEnqueuer`, `SYNC_JOB_KIND`.
- `container`: `Container(sync, agenda, settings, summary=None, pairing=None, close=None)`, the set the api serves; `sync` is a `SyncControl`; `summary` is `None` while summaries are off; `close` is an async function the api's lifespan awaits at shutdown (the distributed api's Redis connections), `None` when there is nothing to release.

## Behaviour
### SyncService(adapters, secrets, events, clock, *, sleep=asyncio.sleep, states=None)
Single-process mode: it fetches. With `states` (a `SyncStateStore`; `app.py` always passes one) every state it remembers is also written to the store, `state(source)` answers from memory first and then from the store (so the last result survives a restart), and `forget`/`purge` and a sync that finishes after a disconnect delete the stored state too. A store error never fails a sync: it is logged by exception class only and the in-memory copy still answers. The write is a small upsert done inline (decision 0074).
- `sync(source) -> SyncState` and `sync_all() -> list[SyncState]` (concurrent; one source's failure does not touch the others). An unknown source raises `UnknownSourceError`. Source failures are returned as state, never raised.
- Window: `horizon_window(clock.now() in UTC)`: midnight 14 days before today to midnight 60 days after it. The fetch gets the credentials from `secrets.get(source)`; after a fully successful fetch the result goes to `events.replace(source, window, events)`, which deletes the source's stored events in that window that the fetch no longer returns (removed or moved at the source) and upserts the rest, in one transaction. Any failure (`reconnect`, `error`, no credentials) leaves the stored events as they were; events outside the window are never pruned (decision 0028).
- Result per source, kept in memory and, with `states`, in the `SyncStateStore`: `SyncState(source, status, message, at)` with `status` `syncing | ok | reconnect | error`.
  - `syncing`: set at the start of `sync()` (and by `mark_syncing`), "Sync in progress"; always replaced by one of the three below.
  - `ok`: "Synced N items" (N is the number of events `replace` wrote).
  - no stored credentials: `reconnect`, "Not connected"; the adapter is not called.
  - `AuthExpired`: `reconnect`; not retried.
  - `TransientError`: up to 3 retries (4 fetches), sleeping 1, 2, 4 seconds; each retry is logged with source, attempt, delay and reason; then `error` with the reason.
  - `FatalError`: `error` with the reason; not retried.
  - `core.errors.SecretStoreError`: `error`, message exactly `secret store unavailable`.
- Each retry and give-up is logged with the source, attempt, delay and reason in the message text (and as `extra` fields). The reason, and the text of a `FatalError` warning, is `safe_message(error_text(exc))`: redacted, then at most 200 characters, in the message and in the `reason` field alike (decision 0056). No log record from `sync.py` carries adapter text any other way.
- Every message kept in a `SyncState` (from a sync, `record_error` or `error_state`) goes through `core.redact.redact`, then `trim(…, 200)`, before it is stored or returned: email addresses become `[email]`, digit runs of 6+ digits become `[number]`, and the whole message, prefix included, is at most 200 characters (decision 0052). Adapters must still keep credentials out of their error text (`docs/contracts/adapters.md` rule 6); redaction is the second line, not the first. `ConnectResult.message` gets the same treatment (see `SettingsService.connect`). The shared helper is `errors.safe_message`.
- Syncs of one source are serialised. `state(source)`, `forget(source)`, `record_error(source, message)`, `sources()`.
- Any other exception (a bug, a database failure) propagates, but first sets the state `error` "Sync failed unexpectedly" so the source is never left `syncing`.
- `forget(source)` while a sync of that source runs: the running sync finishes but does not remember its result, so a disconnect is not undone (decision 0026). That sync also calls `events.delete_source(source)` after its write, so its events do not outlive the disconnect (decision 0029).
- `purge(source)` (async): `forget(source)`, then `events.delete_source(source)` on a worker thread. `SettingsService.disconnect` calls it.
- `mark_syncing(source) -> SyncState`: records `syncing` without fetching; unknown source is `UnknownSourceError`.

### AgendaService(events, clock, tz)
- `day(date)`, `week(date)` (Monday start), `month(date)`, `between(window)`: events in the window, in `tz`, **re-scored** with `core.scoring.urgency(event, clock.now().astimezone(tz))` (the stored urgency is ignored), ordered by `start` (else `due`) then id.
- `today() -> date` and `tz` (property): the calendar day it is now in the configured timezone, and that timezone. Views use them to pick the default day and to group events by local day (decision 0038).
- `attention()`: events in the horizon window around today whose rescored urgency is 70 or more, or that are emails with status `owed` or `overdue`; ordered by urgency descending, then time. An assignment overdue by more than 14 days is outside the horizon and is not listed.

### SyncControl and QueuedSyncService(sources, enqueuer, states, events, generations, clock)
`SyncControl` is the Protocol `SettingsService`, the routes and `SyncScheduler` use: `sources()`, `state(source)`, `mark_syncing(source)`, `record_error(source, message)`, `error_state(source, message)`, `async sync(source)`, `async sync_all()`, `async purge(source)`.

`QueuedSyncService` is the distributed api's. It fetches nothing (decision 0074):
- `sync(source)`: unknown source is `UnknownSourceError`; otherwise `SyncEnqueuer.publish_one(source)` (a job stamped with the source's current generation) and returns the `syncing` state. A queue or database failure is logged by class and returned as an `error` state (`QUEUE_FAILED_MESSAGE`), never raised.
- `sync_all()`: `SyncEnqueuer.publish_connected()`; each queued source is returned as `syncing`, every other source as the `SyncStateStore` holds it (left out when it holds nothing). The results arrive later through `state`.
- `state(source)`: `SyncStateStore.get(source)`, i.e. what the normalizer recorded.
- `mark_syncing`, `record_error`, `error_state` return a state stamped with this process's clock and do **not** store it: the normalizer drops a report older than the stored state, and a worker's clock may lag the api's, so an api-stamped row could hide a real result.
- `purge(source)`: `GenerationStore.bump(source)` first, then `EventStore.delete_source` and `SyncStateStore.delete`, each through `asyncio.to_thread`. The bump comes first so a report being applied sees it and the normalizer removes what an older generation wrote (`ReportSink`, `docs/contracts/core.md`).

### SettingsService(adapters, secrets, sync, integrations=None)
- `integrations` maps a name to a credential-only `IntegrationAdapter` (today `gemini`, field `api_key`; decision 0058). A name that is also a source is a `ValueError`. An integration is listed by `status()` after the sources, connected by `connect` and deleted by `disconnect` exactly like a source (merge, `validate`, write-only `set + last4`, redacted messages, `secret store unavailable`), with these differences: it has no sync, so `ConnectResult.sync` and `SourceSettings.sync` are `None` (a store failure still reports an error state, which is not remembered), `connect` does not call `mark_syncing` and the caller must not sync it (a sync is due exactly when `result.sync` is not `None`), and `disconnect` has no events to purge. `SyncService`, `sync_all`, the scheduler and the agenda never see it. Its `validate` may raise `TransientError`/`FatalError` like a source's; `connect` words them the same way.
- `connect(source, creds) -> ConnectResult`: loads the stored credentials and overlays the submitted fields whose value is not blank (`value.strip()` non-empty); a blank or whitespace-only field keeps the stored value, and clearing a field means disconnect then reconnect (decision 0052). `adapter.validate(merged)` sees that merged set, stored keys included. If `ok`, stores each key of `{**merged, **updated_creds}` whose value differs from the stored one with `secrets.set`, then marks the source `syncing` and returns that state. It does not sync: the caller runs `SyncControl.sync(source)` afterwards (decision 0025; in distributed mode that queues a job for the workers and no sync runs in the api, decision 0074). If not `ok`, or `validate` raises `AuthExpired`/`TransientError`/`FatalError`, returns `ok=false` with a message and stores nothing. Every message that comes from the adapter or wraps its error text (accepted, rejected, `Could not validate credentials: …`) goes through `errors.safe_message` (redact, then 200 characters, prefix included) before it is returned (decision 0052). A store failure, on the read or on a write, returns `ok=false`, message `secret store unavailable`, and an error state; a read failure validates and stores nothing, a write failure leaves the keys written before it stored (there is no per-key rollback). Unknown source: `UnknownSourceError`.
- `status() -> list[SourceSettings]`: per registered source, per key `{set, last4}` (core `SecretStatus`) plus its `SyncState` or None (read through `SyncControl.state` off the event loop, so in distributed mode it is the state the normalizer recorded). Never a value. If the store is unavailable the entry has no keys and an error state, which is reported but does not replace the remembered sync result.
- `disconnect(source) -> SourceSettings`: deletes every key, then `SyncControl.purge(source)`: forgets the sync state (the stored one too) and deletes every stored event of the source, dated or not (decision 0029); in distributed mode it also bumps the source's generation so work in flight is dropped (decision 0074). If the secret store is unavailable it returns the error state and neither forgets nor deletes. Unknown source: `UnknownSourceError`.

### SummaryService(agenda, store, provider, clock, tz, *, include_email=False)
Opt-in (decision 0004): the composition root builds it only when `Settings.summary_enabled` is true, so with the default there is no provider and nothing is sent.
- `get(day) -> SummaryResult(summary, provider, cached)`: a stored summary for `day` is returned at once (`cached` true, `provider` the configured provider's name) and the provider is not called. Otherwise the events are `agenda.day(day)` plus, when `day` is today in `tz`, `agenda.attention()` (deduplicated by id); email events are dropped unless `include_email`; due dates are converted to `tz`. The prompt is `core.summary.build_prompt(events, include_email, day)`; one provider call; a success is stored and returned (`cached` false).
- `SummaryProviderError` (incl. `SummaryRateLimited`) from the provider, logged by provider and class of failure: return `store.latest_before(day)` (an earlier day only) as `provider="stored"` (`cached` true), else `template_summary` as `provider="template"` (`cached` false). Fallbacks are never stored, so the next request retries. Any other exception propagates. No events to describe: the provider is not called; the template is returned, unstored.
- The key is not read here. `GeminiSummaryProvider` reads `("gemini", "api_key")` from the `SecretStore` on every call, so a key saved in Settings applies to the next request without a restart, and a deleted key makes the provider fail with `SummaryProviderError`, which is the fallback below. A summary already stored for a day stays; deleting the key does not remove it (decision 0058). The opt-in is still `Settings.summary_enabled`: saving a key never turns summaries on.
- One lock serialises requests, so concurrent requests for a new day make one provider call. Store calls run through `asyncio.to_thread`. There is no expiry: a summary built before the day's first sync stands until the next day. Decisions: 0034, 0035, 0040.
- `for_day(day) -> str | None`: the summary as text (`headline`, then `Priorities: a; b`, then `Heads up: c`), the method the web page calls on `container.summary`.

### SyncScheduler(sync, interval_minutes, *, sleep=asyncio.sleep, enqueue=None)
- `start()` creates one asyncio task on the running loop (a second call does nothing); `stop()` cancels it and waits. `run()` is `sync_all`, then a wait of `interval_minutes`, forever.
- A round that raises is logged at WARNING with the exception class only (never its message, which may carry a credential) and the loop carries on. Cancellation is the only way it ends.
- `api.create_app(..., sync_interval_minutes=N)` starts it in the lifespan and stops it at shutdown; `app.py` passes `Settings.sync_interval_minutes`. The summary is not scheduled: `SummaryService.get` builds it on the first request for a day (decision 0053).
- Exactly one of `sync` and `enqueue` is given (else `ValueError`). With `sync` a round is `sync_all` (single-process mode). With `enqueue` (a `SyncEnqueuer`, distributed mode) a round publishes jobs and fetches nothing.

### SyncEnqueuer(sources, secrets, queues, clock, ids, *, generations=None)
- `publish_connected() -> list[str]` publishes for each connected source (below) and names the sources it published; `publish_round() -> int` is its length. `publish_one(source)` publishes one job whether or not the source is connected (the worker answers an unconnected one with a `reconnect` report) and lets a store or queue error propagate; it is what `QueuedSyncService.sync` calls. With `generations` every job carries `generations.current(source)` read at publish time, without it `0`. Per source, in `publish_connected`: for each name in `sources` whose credentials are stored, one `Job(kind=SYNC_JOB_KIND, source, window=horizon_window(clock.now()), correlation_id=ids.new_id(), id=ids.new_id())` on `queues[source]`; returns how many were published. A source with no credentials is skipped (the job would only come back as a reconnect). A queue that raises is logged with the exception class only (never its message) and the round goes on with the next source. A job carries no credential (decision 0070).

### Secret store errors
Services catch `core.errors.SecretStoreError` (decision 0024) and report only the fixed text `secret store unavailable`; the error's own message is never copied into a state, result or log line.

### PairingService(store, tokens, clock, *, base_url=None)
- `services/pairing.py`; rules in `core/pairing.py` (constants, hashing, `FailureLimiter`), ports `DeviceStore` and `TokenSource`. `Container.pairing` is `None` when not configured. Decision 0057.
- `base_url` is `https://<first CC_ALLOWED_HOSTS entry>` or `None` (then no code can be shown). `start_pairing()` mints a one-time token (replacing any live one) and returns `PairingOffer`. `pair(token, device_name)` consumes it and returns `IssuedTokens`; `refresh(refresh_token)` rotates; `authenticate(access_token)` returns the device id or `None`; `devices()`; `revoke(id) -> bool`.
- Only SHA-256 digests reach the store. Every rejection is `CredentialRejectedError`; five failures lock pairing (and, separately, refresh) for 60 s, raised as `PairingLockedError(retry_after_seconds)`. Reuse of a swapped refresh credential deletes the device. Logs carry reason codes and device ids, never a token.

## Not built yet
- Collapsing the scheduler's queued jobs while a source is down (decision 0070).
