# Map

Readable copy of the boundaries enforced in `pyproject.toml` (`[tool.importlinter]`, run by
`mise run arch`). If they disagree, pyproject.toml wins; fix this file.

## Dependency table (a layer may import only what its row lists)
| Layer (`src/command_center/...`) | May import | Role |
|---|---|---|
| `core` | nothing in the app | pure: schema, ports (Protocols in `core/ports.py`), errors, urgency scoring, redaction, window math, URL check (`urlcheck`) |
| `services` | core | application logic against ports: sync (in-process `SyncService`, or the distributed api's `QueuedSyncService`, both a `SyncControl`), the sync scheduler, agenda, settings, summary, the `Container` the api serves |
| `adapters` | core | Canvas, CalDAV (Apple), iCal feed, Gmail, weather, summary providers, keyring store, queue impls, menu-bar |
| `storage` | core | SQLite (default) and Postgres persistence: events, sync states (with the generation each row was written under), per-source generations, the report sink that writes a report's events and state in one transaction (`storage/sqlite_sink.py`, decision 0075), summaries, devices |
| `api` | services, core, and `web` (only `api/factory.py`, to mount the pages) | REST under `/v1` (`api.create_app(container)`); `docs/generated/openapi.json` is the contract |
| `web` | services, core, `pairing` (QR only) | Jinja2 + HTMX views |
| `workers` | services, core | distributed mode only: one sync worker per source, the normalizer, the scheduler role (`python -m command_center.workers`) |
| `desktop` | services, core | macOS menu-bar launcher |
| `pairing` | services, core | the pairing QR code (`pairing/qr.py`); the token logic is `core/pairing.py` and `services/pairing.py` (decision 0057) |

`core` also may not import httpx, sqlalchemy, fastapi or keyring. No layer imports `app`.

## Composition roots (the only files that build concrete infrastructure)
- `src/command_center/app.py` (API process): `build_adapters()`, `build_integrations()` (the credential-only Gemini key), `build_container()` (registers the five sources and the integrations; builds the summary only when `summary_enabled`), `build_app(settings)`, the production `create_app()`, and `main()`
- `src/command_center/workers/__main__.py` (distributed mode: `--source NAME`, `--normalizer`, `--scheduler`; the loops are `workers/sync_worker.py` and `workers/normalizer.py`; decision 0070)
- `src/command_center/desktop/main.py` (menu-bar app; the rumps-free parts are `desktop/menu_title.py`, `launch_agent.py`, `server_process.py` and `events_client.py`)

The last two live inside layers that may not import adapters/storage; import-linter ignores exactly those
two files for that rule.

## Vendor SDK, one adapter file each
| SDK | The only importer |
|---|---|
| caldav | `adapters/caldav_apple.py` |
| googleapiclient, google_auth_oauthlib | `adapters/gmail.py` |
| google-genai (`google`) | `adapters/summary_gemini.py` (see the note below) |
| keyring | `adapters/keyring_store.py` |
| redis | `adapters/queue_redis.py` |
| rumps | `adapters/menubar_rumps.py` |

`keyring_store.py`, `caldav_apple.py`, `summary_gemini.py`, `gmail.py`, `weather.py`, `queue_redis.py` and `menubar_rumps.py` exist. `system_tokens.py` (the real `TokenSource`) is also built.
Other built adapters: `net_guard.py` (DNS-time SSRF check), `system_clock.py` (the real `Clock`), `ical_feed.py` (LearningSuite feeds), `ical_events.py` (iCalendar parsing shared by `ical_feed.py` and `caldav_apple.py`), `summary_ollama.py` (the local summary provider), `inprocess_queue.py` (the default `JobQueue`) and `json_log.py` (JSON log formatter), `inprocess_reports.py` (in-process `ReportStream`), `file_secret_store.py` and `secret_backend.py` (container secret store and its chooser), `source_registry.py` (the five source adapters), `system_rng.py` and `system_ids.py` (the real `Rng` and `IdSource`). `queue_redis.py` also holds the Redis `ReportStream`.

`adapters/gmail.py` also imports google-auth (`google.oauth2`, `google.auth`), which shares the `google`
namespace with google-genai, so the google-genai contract lists `adapters.gmail -> google` as an ignored
import (decision 0043). `mise run arch` therefore no longer proves that Gmail avoids `google.genai`;
review enforces it. `gmail_mail.py` (the owed-reply heuristic) and `weather.py` import no SDK.

## Settings
`src/command_center/config.py` (`Settings`, env prefix `CC_`) is imported by composition roots only; no
layer reads the environment itself. Enforced by review only: no import-linter contract covers it yet. Storage's `sqlite.py` takes the database URL as a parameter.

## Where things live
- Rules for agents: `AGENTS.md`; Claude-only: `CLAUDE.md`, `.claude/`
- Command contract and tool versions: `mise.toml`; guards and hooks: `scripts/hooks/`
- Decisions and reasons: `docs/decisions/`; behaviour per package: `docs/contracts/`
- Generated (never hand-edit): `docs/generated/`
- Operations: `docs/runbook.md`; running the Docker stack: `docs/distributed-mode.md`

## Assumptions
- Single user, single Mac; the phone is a separate client in another repo.
- Default mode is one process with SQLite and an in-process queue; distributed mode is opt-in
  (`docs/decisions/0001-two-modes.md`).
