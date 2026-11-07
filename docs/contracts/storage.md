# Contract: storage

Persistence. Implements storage ports from core; SQLAlchemy lives here.

## Behaviour
- `sqlite.SqliteEventStore` implements `EventStore` (sync SQLAlchemy 2). `create_event_store(database_url)` is the factory: it creates the parent directory of a SQLite file, creates the tables if missing and returns the store; `close()` releases the pool. Any SQLAlchemy URL works, so Postgres needs no code change (its driver is the optional `distributed` extra).
- Table `events`, primary key `(user_id, id)`. Columns mirror `Event`; `raw` is JSON (written through `model_dump(mode="json")`, so non-JSON values come back as their JSON form). Datetimes are stored in UTC and returned timezone-aware in UTC (equal to the instant written, not the zone it was written in). `anchor` is an indexed column holding `start`, else `due`.
- `upsert` merges by `(user_id, id)` in one transaction; a repeated id in a batch keeps the last event; an event whose `user_id` differs from the argument raises `ValueError` before anything is written. `query` follows the matching rules in `docs/contracts/core.md` exactly (time is `start` else `due`; a span, `end` after the time, matches on overlap; a point matches in the half-open window; undated events never match; ordered by time then id). Both stores run the shared suite `tests/test_event_store_contract.py`.
- The URL comes from `config.Settings.database_url` (env `CC_DATABASE_URL`, also `DATABASE_URL`; default `sqlite:///<data_dir>/command_center.db` with `data_dir` `~/.command-center`). Composition roots pass it in; storage never reads the environment.
- The engine is created with `hide_parameters=True`: a failed statement's error text names the SQL but not the bound values, so event titles and `raw` fields never reach an exception message or a log (decision 0027).
- Ordering by id uses the database's collation. SQLite's default is bytewise, which equals the in-memory fake; a Postgres deployment must use a `C` collation (or the suite will tell us).

## Not built yet
- Schema migrations (tables are created if missing, never altered) and a cache of fetched items with per-source last-sync times.
- Never stores secrets (those are in the keychain) or email bodies.
