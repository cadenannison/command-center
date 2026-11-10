# 0232. The completions table stays in the ledger base, and a guard test bans a bare create_all

Status: accepted. Refines the migration of 0131.

Context: `ensure_completions_table` copies the old `done_at` and `done_by` into `item_completions`, and only in the transaction that creates the table. `LedgerBase.metadata` holds both ledger tables, so a bare `LedgerBase.metadata.create_all(engine)` on a database that already has `item_ledger` would create `item_completions` empty, and the copy would never run: every completion from before 0131 would silently disappear from history.
Decision: Keep `CompletionRow` on `LedgerBase` and add `tests/test_schema_guard.py`, which parses every module under `src/command_center` that mentions `LedgerBase` or `CompletionRow` and fails on any `<x>.metadata.create_all(...)` without `tables=`. The test also checks its own checker on three snippets. Today the two calls in `sqlite_ledger.py` and `sqlite_completions.py` both name their tables.
Alternative: Give `CompletionRow` its own declarative base. Not taken: `tests/test_ledger_migration.py` and `tests/test_ledger_completions.py` build their legacy databases with `LedgerBase.metadata.create_all(engine)` and then `DROP TABLE item_completions`, which would fail, and the task card for this change allows new tests only (`tests: new-only`). That is the cleaner design, and the better fix once those two fixtures may change.
Reason: The guard closes the hazard for production code today without touching existing tests. It does not stop a test or a script outside `src` from doing the bare call, which is where it is harmless.
Where: `tests/test_schema_guard.py`; `docs/contracts/storage.md`.
Revisit when: A task card says `tests: modify` for the two migration fixtures; then move `CompletionRow` to its own base and drop the guard.
