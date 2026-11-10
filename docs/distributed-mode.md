# Distributed mode

One process per job instead of one process for everything. Opt-in (decision 0001): the default is still a single process with SQLite and an in-process queue. Decisions: 0070 (roles, queues, breaker), 0071 (report stream, shared sync state), 0072 (the one non-loopback bind) and 0090 (what that bind trusts), 0073 (file secret store, Gmail), 0074 (the api reads shared state, connect only enqueues, disconnect cancels work in flight), 0085 (a failed publish is an error state per source; the disconnect order and its two failure results), 0086 (the purge bumps the generation again), 0075 (the generation is stored with the rows and a report is checked and written in one transaction), 0076 (compose builds the image in the api service only), 0077 (the compose password file lives outside the repo), 0078 and 0079 (the smoke and report scripts).

`Dockerfile` and `docker-compose.yml` were written without a Docker daemon. The stack has since been built and started once on a real machine: `docker compose build api` then `up --no-build` brought up all 10 containers and the api passed its health checks (decision 0076). That is all that has been observed. Still not run, and marked "not yet observed" where they come up: the chaos tests and the Redis code paths against a real Redis, the Postgres cases of the database tests (see Known gaps), what `up --no-build` does when the image has not been built, and the Gmail workaround below.

## Architecture

```mermaid
flowchart LR
    subgraph host["Your Mac (127.0.0.1 only)"]
        browser["Browser / phone via Tailscale Serve"]
    end
    browser -->|"127.0.0.1:8765"| api["api\n(CC_BIND_ALL=1)"]
    sched["scheduler\n--scheduler"] -->|"one sync job per connected source,\nevery CC_SYNC_INTERVAL_MINUTES"| redis[("redis")]
    redis -->|"cc-canvas jobs"| wc["worker-canvas"]
    redis -->|"cc-apple_calendar jobs"| wa["worker-apple-calendar"]
    redis -->|"cc-learningsuite jobs"| wl["worker-learningsuite"]
    redis -->|"cc-gmail jobs"| wg["worker-gmail"]
    redis -->|"cc-weather jobs"| ww["worker-weather"]
    wc & wa & wl & wg & ww -->|"SyncReport: events + window,\nor reconnect / error"| redis
    redis -->|"cc-reports stream"| norm["normalizer\n--normalizer"]
    norm -->|"ReportSink.apply: events + state\nin one transaction"| pg[("postgres")]
    api --> pg
    secrets[["secrets.json (0600)\nvolume cc-data"]] -.-> api & wc & wa & wl & wg & ww & sched
```

- A job carries a source name, a window and ids; never a credential. Workers read credentials from the secret store themselves.
- The api fetches nothing and writes no source events; it writes only the user's own item marks, notes and local tasks. Connecting a source validates and stores the credentials, then queues one sync job; `GET /v1/settings` and the Settings page show the state the normalizer recorded in the shared database (0074).
- A worker fetches under `RetryPolicy` and a per-source `CircuitBreaker`; it never writes events. The normalizer is the only writer of events and sync state.
- Each source has a generation number in the database. Disconnecting bumps it; every job carries the number current when it was queued, the worker copies it into its report, and the normalizer applies a report only if its number is the current one, checked in the same transaction that writes the events and the state, which are stamped with it (0074, 0075). A report that is not current is dropped, and so is whatever an older generation left behind.
- The item ledger (check-offs, notes, completions and removals seen at the source, decision 0120) is written in the same transaction as the events. In the normalizer that is inside `ReportSink.apply`, after the generation check: a report of an old generation, or one older than the stored state, writes no ledger rows, and a crash after the write and before the acknowledgement leaves the same rows after redelivery, because the times come from the report. Purging an old generation (a disconnect) deletes its ledger rows and notes with its events (decisions 0121, 0127). The api writes the user's own check-offs, notes and local tasks directly; those are never touched by a sync or by a disconnect of a source.
- Redis streams give at-least-once delivery. Every consumer is idempotent, so a repeat changes nothing.

## Failure walkthrough

| What fails | What happens | Where it is tested |
|---|---|---|
| A worker is killed during a fetch | The job is never acked; after the visibility timeout (5 min) it is redelivered with `attempt + 1`. Nothing was published, so there are no duplicate events. | `test_chaos_distributed.py` |
| A worker is killed after it published the report, before the ack | The job is redelivered and a second, identical report is published. `EventStore.replace` of the same set leaves the same rows. | same |
| The normalizer is killed in the middle of applying a report | With the sink (the deployed normalizer) the events and the state are one transaction, so a kill leaves both or neither; the report is unacked and is redelivered, and applying it again gives the result of an uninterrupted run. A normalizer without a sink writes events, then state: the redelivered `replace` changes nothing and the state is then recorded. | `test_normalizer_atomic.py` (sink), `test_chaos_distributed.py` (without a sink) |
| A source answers with a transient error | The job is retried with growing, jittered delays (5 attempts by default); the worker counts each failure toward its breaker. After the last attempt the job is dead-lettered and an `error` report records the state. | `test_sync_worker.py`, chaos |
| A source keeps failing | After 5 consecutive transient failures the breaker opens: the worker stops consuming, jobs wait in Redis untouched, and no attempt is spent. After 5 minutes it lets one trial through; success closes it. An answer from the source such as a rejected credential or a bad request also closes it. | `test_sync_worker.py`, chaos |
| A job can never succeed (poison) | A `FatalError` is dead-lettered at once; a job that kills every worker that takes it is dead-lettered once its attempts run out. Dead letters are kept and listed, never replayed (0049). | `test_job_queue_dead_letter.py`, chaos |
| A credential is rejected or missing | A `reconnect` report is published and the job is acked. No retry, no breaker count. The api reads the stored state and shows Reconnect. | `test_sync_worker.py`, `test_distributed_connect.py` |
| Redis is down | The scheduler logs the exception class and tries again next round; workers and the normalizer cannot consume. A connection error that reaches the top of a role ends its process (the heartbeat and the loop share one task group) and `restart: unless-stopped` starts it again. The heartbeat only shows the process's event loop is alive, not that jobs are flowing. | `test_sync_enqueuer.py` |
| An old report arrives after a newer one | The normalizer acks and drops it. | `test_normalizer.py` |
| A source is disconnected while its job is in flight | The disconnect bumps the generation and deletes the events and state. The report the worker then publishes carries the old number, so the normalizer acks and drops it: no events or state come back. If the worker dies before its ack, the redelivered job (old number too) is dropped the same way. | `test_chaos_disconnect_sink.py` (the deployed normalizer), `test_chaos_disconnect.py` and `test_normalizer_generation.py` (without a sink) |
| A disconnect lands while the normalizer is applying a report | The apply takes a lock on the source's generation row, so on Postgres the disconnect's bump waits for it and its purge then removes what was written; on SQLite the database's write lock does the same. If the bump committed first, the check inside the transaction sees it and nothing is written. The check after the write stays as a backstop: if the number moved, the normalizer deletes the source's rows of an older generation, never a newer connection's. | `test_normalizer_atomic.py`, `test_report_sink.py`, `test_normalizer_generation.py` |
| The normalizer dies between writing a report and the check that follows | The report is unacked and redelivered. The bump is already visible, so the redelivery is dropped, and dropping also deletes the source's events and state whose generation is below the current one: the source ends empty. Dropping again does nothing. Rows of a newer connection are kept. | `test_normalizer_atomic.py` (in-process and Redis) |
| Two normalizers, a disconnect and a reconnect | A slow normalizer holding a report from before the disconnect drops it (or undoes its own write) without touching what the other applied for the new connection: only rows of an older generation are deleted. | `test_normalizer_atomic.py` |
| Redis is down when a source is connected or Sync is pressed | The api logs the exception class and shows an `error` state for that call ("Could not queue the sync"), for `POST /v1/sync` once per connected source whose publish failed (the others are still queued); the next scheduled round queues it. Nothing is stored for the failed call. | `test_distributed_connect.py`, `test_queued_sync_publish_failure.py` |
| The database fails during a disconnect | The generation is bumped first. If that bump fails nothing is deleted and the api shows an `error` ("Could not disconnect; nothing was removed"). If the delete of events and state fails after the credentials were deleted, the api shows "Disconnect incomplete"; the bump already made the normalizer drop every report and job queued before it, and disconnecting again, or the first report applied after a reconnect, removes the rest; until then the old state and events stay visible. The purge bumps the generation a second time before it deletes, so a job published between the first bump and the credential delete is dropped too (0086); a disconnect ends on the stored number plus two. | `test_settings_disconnect_order.py` |

The log lines for retry, give-up and dead-letter carry `error_class` (the exception's class name), never its message, because a message may hold a credential (0051).

## How to run

Requirements: Docker with Compose v2.

The Postgres password lives in a file outside the repo, `~/.config/command-center/compose.env`, and every compose command passes it with `--env-file`. Create it once:

```sh
mkdir -p -m 700 ~/.config/command-center
chmod 700 ~/.config/command-center
( set -C; umask 077; printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 16)" > ~/.config/command-center/compose.env )
chmod 600 ~/.config/command-center/compose.env
```

`set -C` makes the redirect refuse to overwrite an existing file, which is what you want: the Postgres volume keeps the first password, so a new one in the file would no longer match it (to start over, `down -v` first). `CC_TZ=...` may go in the same file; it is optional.

Then build and start (the flag goes before the subcommand, and `build` needs it too, because compose reads the password while parsing the file):

```sh
docker compose --env-file ~/.config/command-center/compose.env build    # builds the image once, through the api service
docker compose --env-file ~/.config/command-center/compose.env up -d --no-build
docker compose --env-file ~/.config/command-center/compose.env ps       # every service should become healthy
curl http://127.0.0.1:8765/v1/health
```

Only the `api` service has a `build:` block; the scheduler, normalizer and workers all use `image: command-center:local` and add no build of their own, so Compose has one build to run and no parallel builds of the same tag to race (0076; observed: with `build:` on several services for the same tag, `docker compose up --build` failed with `target worker-gmail: failed to solve: image "docker.io/library/command-center:local": already exists`). The order matters: build before `up`. `--no-build` stops `up` from building anything, so a missing image is an error (expected, not yet observed: Compose then tries to pull `command-center:local` from a registry and fails) instead of a build you did not ask for. After a code change, run `docker compose --env-file ~/.config/command-center/compose.env build`, then `docker compose --env-file ~/.config/command-center/compose.env up -d --no-build` to recreate the containers from the new image.

Why the file is outside the repo (0077): the password is a secret and a `.env` in the working tree can be read by anything that works in the repo, including coding agents, and can end up in a commit or a backup of the project folder. The agent sandbox that edits this repo denies reads of `.env` (it breaks the test run too), so the file would also have to be an exception to that rule. `docker-compose.yml` keeps `POSTGRES_PASSWORD` required with no default: a command that is not given the file stops with "set POSTGRES_PASSWORD" instead of starting Postgres with a guessable password. Exporting `POSTGRES_PASSWORD` in your shell also satisfies it, and wins over the file.

Open `http://127.0.0.1:8765/`. The api is the only published port and it is bound to `127.0.0.1`; redis and postgres are on the compose network only. `CC_BIND_ALL=1` is set on the api service only, because inside a container uvicorn must listen on `0.0.0.0` for the published port to work (0072). Do not add it to any other service and do not change the published port to a bare `8765:8765`: `tests/test_compose_file.py` fails if you do.

Connect sources on the Settings page as usual. Credentials are written to `/data/secrets.json` (mode 0600) on the `cc-data` volume, which the api and every worker mount (`CC_SECRET_BACKEND=file`, 0073). That is weaker than the OS keychain: anyone who can read the volume can read the credentials. Use this mode on a machine only you can reach.

Useful commands:

```sh
docker compose --env-file ~/.config/command-center/compose.env logs -f worker-canvas normalizer   # JSON lines, one per event
docker compose --env-file ~/.config/command-center/compose.env stop worker-gmail                   # jobs for gmail queue up and wait
docker compose --env-file ~/.config/command-center/compose.env down                                # keep the volumes
docker compose --env-file ~/.config/command-center/compose.env down -v                             # also deletes data and credentials
```

Settings that matter (all `CC_`-prefixed; compose sets the first four): `CC_MODE=distributed`, `CC_REDIS_URL`, `DATABASE_URL`, `CC_SECRET_BACKEND=file`, `CC_TZ`, `CC_SYNC_INTERVAL_MINUTES` (default 30, used by the scheduler role).

### Smoke test

With the stack up, `bash scripts/smoke-distributed.sh` checks it through the api and `docker compose --env-file`: health, connect weather, sync, no duplicate events after killing and starting `worker-weather`, sync state and events unchanged after killing and starting the normalizer, and a disconnect that leaves nothing behind (also after another normalizer restart). It prints PASS or FAIL per step and exits 1 on any FAIL. Settings: `COMPOSE_ENV_FILE` (default `~/.config/command-center/compose.env`), `API_URL` (default `http://localhost:8765`), `CC_SMOKE_LAT` and `CC_SMOKE_LON` (default: a generic city), `CC_SMOKE_SETTLE` (seconds to wait after a restart, default 10). It refuses to run when weather is already connected, never prints a credential or the coordinates, and never reads the env file; it only hands its path to compose (decision 0078; the counts use `GET /v1/events` over a window, decision 0079). Not yet observed: it has been syntax-checked and shellchecked, not run against a real stack. A scheduler round during the normalizer restart can fail the "state unchanged" step; run it again.

### Chaos tests against a real Redis

```sh
docker run --rm -d -p 127.0.0.1:6380:6379 --name cc-test-redis redis:7-alpine
CC_TEST_REDIS_URL=redis://127.0.0.1:6380/15 uv run pytest tests/test_chaos_distributed.py \
  tests/test_chaos_disconnect.py tests/test_chaos_disconnect_sink.py tests/test_normalizer_atomic.py tests/test_report_stream_contract.py \
  tests/test_job_queue_dead_letter.py --no-cov
docker stop cc-test-redis
```

They use a throwaway key prefix and clean up after themselves. Without `CC_TEST_REDIS_URL` the Redis cases are skipped and the same scenarios run against the in-process backends.

The database tests (`tests/test_state_generation_column.py`, `tests/test_report_sink.py`) run on SQLite always and on Postgres when `CC_TEST_POSTGRES_URL` is set, for example `postgresql+psycopg://cc:password@127.0.0.1:5433/postgres`. Each test creates a schema of its own and drops it afterwards, so any database you may create schemas in will do.

## Gmail in a container

Gmail's sign-in uses `InstalledAppFlow.run_local_server`: it opens a browser on the machine running the app and listens on a loopback port for Google's redirect. A container has no browser and the redirect cannot reach it, so pressing Connect on the Gmail settings page in the compose stack will not complete (0073).

Workaround: connect Gmail once on a machine with a browser, then hand the result to the stack.

1. Run Command Center normally on that machine with `CC_SECRET_BACKEND=file CC_DATA_DIR=$HOME/cc-gmail-data command-center`, connect Gmail in Settings (see `docs/gmail-setup.md`), then stop it.
2. Copy `$HOME/cc-gmail-data/secrets.json` into the volume, for example `docker compose --env-file ~/.config/command-center/compose.env cp $HOME/cc-gmail-data/secrets.json api:/data/secrets.json`, and make sure it is mode 0600 and owned by the `cc` user (`docker compose --env-file ~/.config/command-center/compose.env exec -u root api chown cc:cc /data/secrets.json`, then the same with `chmod 600 /data/secrets.json`). This replaces every credential in the volume, so do it before connecting other sources, or merge the `gmail` entry by hand.
3. Google expires the sign-in after 7 days while the consent screen is in Testing (0003). Repeat steps 1 and 2 weekly; until then Gmail shows Reconnect.

## Trust boundary

`CC_BIND_ALL=1` makes the api listen on every interface of its container, and the api treats a request with a loopback `Host` (`localhost`, `127.0.0.1`) as the local user, with no token (`api/auth.py`). The api does not look at the peer address, and could not usefully: Docker delivers a published port's traffic from the bridge gateway, not from the host's loopback, so the peer of a legitimate browser request is not loopback either. The consequence is that **any container on the compose network that connects to the api can send `Host: 127.0.0.1` and is treated as the local user**. That includes redis and postgres.

The boundary is therefore the compose network, not the api:
- The compose network is trusted. Every service on it is code from this repo or an official image configured in `docker-compose.yml`; nothing else may be attached to it.
- Only the api publishes a port, and only as `127.0.0.1:8765:8765` (`tests/test_compose_file.py` checks only that each quoted `host:port:port` mapping starts with `127.0.0.1:`; that only the api publishes one is a rule for whoever edits the file, not a tested guarantee), so nothing outside this machine reaches it directly. The phone arrives through Tailscale Serve, which adds proxy headers and a tailnet `Host` and so is held to a device token (`api/auth.py`).
- This is a single trusted host. Anyone who can run a container on it, or join the compose network, already has the credentials volume and the database. Do not attach other containers to this network, do not publish redis or postgres, and do not run the stack on a shared machine.

Decision 0090.

## Known gaps

- While a source is down, the scheduler keeps adding one job per round and they all run after recovery; nothing collapses them yet (decision 0070).
- The api and the normalizer create tables on first start (`events`, `sync_states`, `source_generations`; the scheduler only `source_generations`), and add the `generation` column to a `sync_states` table from before 0075 (`ALTER TABLE`, rows stamped with the source's current generation; safe to run from several processes at once); compose starts the normalizer after the api is healthy to avoid a race on an empty database.
- After a connect, Settings shows no state until the normalizer has recorded the first report: the api does not store a "syncing" row, because its clock could stamp it later than the worker's report and hide the result (0074). The connect response itself carries `syncing`.
- A sync the api could not queue (Redis down at the moment of the click) is not retried until the next scheduled round.
- Redis persistence is append-only file on a named volume; a lost volume loses queued jobs and unprocessed reports, which only delays data until the next scheduled round.
- A connect's background enqueue that runs after a quick disconnect queues a job with the new number, so the worker reports `reconnect` for the source and the normalizer stores that state. Single mode behaves the same.
- Jobs and reports carry a new `generation` field and the models forbid unknown fields: roll the api, workers, scheduler and normalizer out from one image together.
- Disconnecting in single mode does not bump the stored generation, so jobs still in Redis from an earlier distributed run are not invalidated if distributed mode is switched on again. The reverse also holds: single-mode state rows keep the number of the row they replace (0 if new), so after switching back to distributed a source whose counter is above 0 can have a row the first apply treats as left over, and it deletes that source's events before writing its report; the next sync restores them.
- Not yet run against a real Redis or Postgres: the Redis cases of `test_chaos_disconnect.py`, `test_chaos_disconnect_sink.py` and `test_normalizer_atomic.py` need `CC_TEST_REDIS_URL`, and the Postgres cases of `test_state_generation_column.py` and `test_report_sink.py` need `CC_TEST_POSTGRES_URL=postgresql+psycopg://...` (see above). Until they have been, the claim that a disconnect's bump waits for an apply on Postgres is argued, not observed. The non-required CI job `integration` now starts a Redis and a Postgres service and runs exactly these files with both variables set (decision 0083); no run of it has been observed yet, so the claim stays unobserved until one is green.
- The disconnect's own deletes (`QueuedSyncService.purge`, after its own bump, the second of a disconnect) are not generation-aware: if the user reconnects and a normalizer applies a report for the new connection within the milliseconds between the disconnect's bump and its deletes, that data is deleted and the next scheduled sync restores it (decision 0075, risk B).
- A leftover written by a normalizer that died between its write and its check *before* the upgrade to 0075 is stamped as current by the migration and is not removed automatically; disconnect and reconnect the source to clear it (decision 0075, risk A).
- A `Normalizer` built without a sink (only tests and tools do; the normalizer role always has one) applies reports the 0074 way: it can leave a write behind when it dies between the write and the check, and two of them can undo each other's writes.
- A disconnect bumps the generation, deletes the credentials, then bumps again as the first step of the purge (decisions 0085, 0086). A sync queued after the first bump and before the credentials are gone carries the old number, so its report is dropped. What stays: a sync queued after the disconnect has finished (a connect's follow-up, the Sync button) carries the final number and, with no credentials, ends as a `reconnect` state row, which is the case in the connect gap above.
