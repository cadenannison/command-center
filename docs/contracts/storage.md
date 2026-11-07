# Contract: storage

Persistence. Implements storage ports from core; SQLAlchemy lives here.

## Behaviour
Nothing yet.

## Not built yet
- SQLite by default (single process, in-process queue); Postgres in distributed mode.
- Schema migrations and a cache of fetched items with per-source last-sync times.
- Never stores secrets (those are in the keychain) or email bodies.
