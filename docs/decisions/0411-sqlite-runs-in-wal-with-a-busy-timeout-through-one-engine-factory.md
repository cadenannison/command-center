# 0411. SQLite runs in WAL with a busy timeout, through one engine factory

Status: accepted

Context: nine storage factories each called `create_engine(url, hide_parameters=True)` on one SQLite file with the rollback journal. A writer that holds the file blocks every reader, which then fails with "database is locked" while a sync writes (audit R07; card 06).
Decision: `storage/engine.py` `make_engine(database_url)` is the only place in `storage/` that calls `create_engine`. It keeps `hide_parameters=True` (decision 0027). For the SQLite dialect it registers a `connect` event that runs `PRAGMA journal_mode=WAL` (skipped for in-memory URLs, where it does not apply), `PRAGMA busy_timeout=5000` and `PRAGMA foreign_keys=ON`. Other dialects (Postgres) get a plain engine with no listener. The nine factories call it.
Alternative: one shared engine for all stores (not taken: it changes container wiring, and each store still owns its pool today; note for later). Also not taken: setting the pragmas only on the busiest stores, which leaves the other connections on the rollback journal.
Reason: the pragmas are per connection, so they must be set where every connection is made, and one function is the only way to keep nine call sites from drifting. A test fails if another `create_engine(` appears in `storage/`.
Consequences: the database is three files (`.db`, `-wal`, `-shm`); a backup must checkpoint first (`PRAGMA wal_checkpoint(TRUNCATE)`) or copy all three (runbook). Foreign keys on may expose an existing violation, which is reported, not hidden. Test code that opens its own engine on the file does not get the pragmas.
Where: `storage/engine.py`, the nine `create_*` factories in `storage/`. Tests: `tests/test_storage_engine.py`.
Revisit when: the stores share one engine, or a store needs a different timeout.
