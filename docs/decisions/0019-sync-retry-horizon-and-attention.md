# 0019. Sync retries, the sync horizon and the attention list

Status: accepted

Context: The card fixes the window (today-14d to today+60d), "retry 3x with backoff" for `TransientError`, and `attention()` = urgency 70+ or email owed/overdue, but not these details.
Decision:
- "Retry 3x" is three retries after the first attempt, so four fetches at most. Backoff is 1, 2, 4 seconds (doubling, no jitter: one user, one Mac, and jitter would need an `Rng`). Only `TransientError` is retried; the sleep is injectable so tests never wait. Every retry and the final give-up are logged with the source, attempt and reason.
- The window is built from local midnights (`services/horizon.py`). `SyncService` has no timezone parameter, so it uses UTC days; `AgendaService` uses its configured zone. The two differ by under a day at the edges.
- `attention()` looks at the same horizon, so an assignment overdue by less than 14 days still appears and an older one does not. It sorts by urgency, highest first, then by time.
- A source with no stored credentials syncs to state `reconnect` ("Not connected"), without calling the adapter.
- The retry count, backoff base, horizon (14 and 60 days) and attention threshold (70) are constants in code, not `Settings`: the card fixes them and nobody has asked to tune them. A request to `POST /v1/sync` waits for the retries, up to 7 seconds per failing source.
- Syncs of one source are serialised by a per-source lock, so two requests cannot fetch at once.
Alternative: Three attempts in total; sync window in the user's timezone (would add a `tz` argument to `SyncService`); attention over a single day or all time; an unconnected source skipped.
Reason: Smallest reading of the card that stays deterministic and bounded. All-time attention would grow without limit; a single day would hide overdue work.
Where: `src/command_center/services/sync.py`, `agenda.py`, `horizon.py`; `docs/contracts/services.md`.
Revisit when: The project manager wants different retry counts, a user-timezone sync window, or an attention list that includes older overdue items.
