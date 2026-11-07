# Map

Readable copy of the boundaries enforced in `pyproject.toml` (`[tool.importlinter]`, run by
`mise run arch`). If they disagree, pyproject.toml wins; fix this file.

## Dependency table (a layer may import only what its row lists)
| Layer (`src/command_center/...`) | May import | Role |
|---|---|---|
| `core` | nothing in the app | pure: schema, ports (Protocols in `core/ports.py`), urgency scoring, redaction, window math |
| `services` | core | application logic against ports |
| `adapters` | core | Canvas, CalDAV (Apple), iCal feed, Gmail, weather, summary providers, keyring store, queue impls, menu-bar |
| `storage` | core | SQLite (default) and Postgres persistence |
| `api` | services, core | REST under `/v1`; `docs/generated/openapi.json` is the contract |
| `web` | services, core | Jinja2 + HTMX views |
| `workers` | services, core | background sources: in-process by default, one per source in distributed mode |
| `desktop` | services, core | macOS menu-bar launcher |
| `pairing` | services, core | QR codes and short-lived phone tokens |

`core` also may not import httpx, sqlalchemy, fastapi or keyring. No layer imports `app`.

## Composition roots (the only files that build concrete infrastructure)
- `src/command_center/app.py` (API process)
- `src/command_center/workers/__main__.py` (worker processes)
- `src/command_center/desktop/main.py` (menu-bar app)

The last two live inside layers that may not import adapters/storage; import-linter ignores exactly those
two files for that rule.

## Vendor SDK, one adapter file each
| SDK | The only importer |
|---|---|
| caldav | `adapters/caldav_apple.py` |
| googleapiclient, google_auth_oauthlib | `adapters/gmail.py` |
| google-genai (`google`) | `adapters/summary_gemini.py` |
| keyring | `adapters/keyring_store.py` |
| redis | `adapters/queue_redis.py` |
| rumps | `adapters/menubar_rumps.py` |

These files do not exist yet; the contracts already name them.

## Where things live
- Rules for agents: `AGENTS.md`; Claude-only: `CLAUDE.md`, `.claude/`
- Command contract and tool versions: `mise.toml`; guards and hooks: `scripts/hooks/`
- Decisions and reasons: `docs/decisions/`; behaviour per package: `docs/contracts/`
- Generated (never hand-edit): `docs/generated/`
- Operations: `docs/runbook.md`

## Assumptions
- Single user, single Mac; the phone is a separate client in another repo.
- Default mode is one process with SQLite and an in-process queue; distributed mode is opt-in
  (`docs/decisions/0001-two-modes.md`).
