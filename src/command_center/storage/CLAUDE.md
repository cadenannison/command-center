# storage

Contract: `docs/contracts/storage.md`. Rules that load here: `.claude/rules/style.md`, `tests.md`.

- Imports `core` only, never `adapters`. SQLite by default; any SQLAlchemy URL works, so Postgres needs no
  code change. Keep SQL valid on both (the contract notes where they differ, such as collation).
- Ledger tables are created through the ledger base, never with a bare `create_all` (decision 0232; a guard
  test in `tests/test_schema_guard.py` enforces it, decision 0247). Do not edit that test to get past it.
- A report's events and its sync state are written in one transaction (`sqlite_sink.py`, decision 0075).
  Check-offs and removals ride in the events' own transaction (decisions 0120, 0121, 0131).
- Column names are persisted identifiers: deprecate, never rename or delete (AGENTS.md).
- Unit tests use SQLite in memory. Never touch the real database under `~/.command-center`.
