---
paths:
  - "tests/**/*.py"
---
- One behaviour per test, named for what is tested and the expected outcome.
- Fake Clock and seeded Rng/IdSource: no real time, no real randomness, no sleeping.
- Mock HTTP with respx at the httpx boundary; use in-memory fakes through ports; never a real network,
  keychain or database server in unit tests (SQLite in memory is fine).
- Build fixtures with builders that parse through the real pydantic schema so they cannot drift from it.
- Integration tests (Redis, Postgres, real services) are guarded by an environment variable and clean up.
- Property tests (hypothesis) for core invariants: window math, urgency ordering, redaction never leaks.
- A flaky test is quarantined with an issue, an owner and a 7-day expiry. No retries on the gate.
