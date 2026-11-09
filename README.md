# command-center
A desktop app to pull all daily, weekly, and monthly info from disparate data sources into a clean visual dashboard.

Personal productivity dashboard: aggregates calendars, Canvas, email and weather into day/week/month
views with an opt-in AI summary. Local-first: the server binds to 127.0.0.1 and secrets live in the OS
keychain.

## Quickstart
```
uv sync                # install dependencies (Python 3.13)
uv run command-center  # start the server on 127.0.0.1:8765
```
Then open http://localhost:8765 and go to Settings to connect your sources: [docs/sources.md](docs/sources.md)
has the setup for each one. The app syncs when it starts and then every 30 minutes
(`CC_SYNC_INTERVAL_MINUTES`). Your credentials are stored in the OS keychain, never in a file, and the
server only answers on your own machine.

First time? [docs/first-run.md](docs/first-run.md) walks through connecting each source and what a good
first sync looks like. To send someone a status that is safe to paste (statuses, last 4 characters, counts,
no secrets), run [`bash scripts/report-state.sh`](scripts/report-state.sh).

AI summaries are off unless you set `CC_SUMMARY_ENABLED=true`; see "Summaries" in [docs/sources.md](docs/sources.md).

More ways to run it:
- **Distributed mode** (Docker: one container per source, Redis, Postgres, opt-in): [docs/distributed-mode.md](docs/distributed-mode.md).
- **Phone pairing** (read-only phone app over Tailscale Serve): [docs/mobile.md](docs/mobile.md). The API notes for the phone repo are in [docs/mobile-api-notes.md](docs/mobile-api-notes.md).

## Security model
1. **Loopback only by default:** the server binds 127.0.0.1; the one exception is an explicit opt-in (`CC_BIND_ALL`) that exists for the API container in distributed mode (it makes the app server listen on all of that container's interfaces; compose still publishes it on 127.0.0.1 only; with it set, any container on the compose network passes the loopback Host check, so that network is trusted and the stack is for one trusted host: [docs/distributed-mode.md](docs/distributed-mode.md#trust-boundary)), and a phone is served only for the tailnet names you list.
2. **Write-only credentials:** secrets live in the OS keychain (or a file secret store in containers); the settings API returns only "set" and the last 4 characters, never a value.
3. **Redaction before AI:** summaries are off by default, and when on, only titles, due dates and trimmed subjects reach a provider, with addresses and numbers stripped and never an email body.
4. **Hashed device tokens:** a paired phone gets short-lived tokens of which only SHA-256 hashes are stored, with a one-time pairing code, rotation on refresh, and a read-only scope plus `POST /v1/sync`.
5. **No secrets in the repo:** configuration comes from the environment or the keychain, tests use only `fake-` credentials, and gitleaks scans every push. Report a problem: [SECURITY.md](SECURITY.md).

## Development
```
mise install && mise run setup   # pinned tools, git hooks, dependencies (needs jq: brew install jq)
mise run check                   # every non-mutating gate; same tasks run in CI
uv run command-center            # API on http://127.0.0.1:8765
```
Rules for contributors and coding agents: [AGENTS.md](AGENTS.md). Layers: [docs/MAP.md](docs/MAP.md).
Decisions: [docs/decisions/](docs/decisions/). Operations: [docs/runbook.md](docs/runbook.md).
