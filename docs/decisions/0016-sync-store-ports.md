# 0016. Store ports are synchronous; no aiosqlite

Status: accepted

Context: `EventStore` and `SecretStore` are ports used from async code (FastAPI handlers, async source adapters). SQLite is the default database, with Postgres possible later.
Decision: Both store ports are plain synchronous methods, and storage uses sync SQLAlchemy 2. `aiosqlite` is not used. Services (not built yet) that run in the event loop call a store through `asyncio.to_thread`.
Alternative: Async ports backed by SQLAlchemy's async engine and `aiosqlite` (and an async driver for Postgres). That gives non-blocking calls without a thread hop, at the cost of async ports everywhere, a second driver per database, and async test plumbing. The keychain (`keyring`) is synchronous only, so `SecretStore` would need a thread hop anyway.
Reason: Personal scale and single-user queries are fast, one sync code path works for SQLite and Postgres unchanged, and a thread hop at the service boundary keeps the loop free without changing the ports.
Where: `EventStore` and `SecretStore` in `src/command_center/core/ports.py`; `src/command_center/storage/sqlite.py`; `docs/contracts/storage.md`.
Revisit when: Store calls are measured blocking the event loop or exhausting the worker thread pool, or distributed mode needs an async database driver. Then write a new record that supersedes this one.
