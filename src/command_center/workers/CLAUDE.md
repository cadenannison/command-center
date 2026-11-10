# workers

Distributed mode only (`docs/distributed-mode.md`, decision 0070). Default mode is one process with an
in-process queue, so changes here must not alter it. Rules that load here: `.claude/rules/layers.md`,
`style.md`, `tests.md`.

- Imports services and core. `__main__.py` is a composition root and the only file here that builds
  adapters and storage; import-linter ignores exactly that file.
- Roles: one sync worker per source (`sync_worker.py`), the normalizer (`normalizer.py`), the scheduler.
- Queue and report stream are the `JobQueue` and `ReportStream` Protocols; Redis is behind
  `adapters/queue_redis.py` only.
- Generation numbers decide which rows are current (decisions 0074, 0075). Read them before touching how a
  report is applied.
