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

AI summaries are off unless you set `CC_SUMMARY_ENABLED=true`; see "Summaries" in [docs/sources.md](docs/sources.md).

## Development
```
mise install && mise run setup   # pinned tools, git hooks, dependencies (needs jq: brew install jq)
mise run check                   # every non-mutating gate; same tasks run in CI
uv run command-center            # API on http://127.0.0.1:8765
```
Rules for contributors and coding agents: [AGENTS.md](AGENTS.md). Layers: [docs/MAP.md](docs/MAP.md).
Decisions: [docs/decisions/](docs/decisions/). Operations: [docs/runbook.md](docs/runbook.md).
