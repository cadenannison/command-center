# core

Contract: `docs/contracts/core.md` (`## Public exports` first, then `## Behaviour`). Rules that load here:
`.claude/rules/style.md`, `.claude/rules/tests.md`. Agent for this layer: `domain-engineer`.

- Pure. Time, randomness and ids arrive as `Clock`, `Rng`, `IdSource` from `ports.py`. `mise run arch` and
  ruff banned-api fail the build on I/O, `datetime.now()`, `random`, environment or globals.
- `ports.py` is the single seam: every Protocol the services depend on lives there. A new port means a
  contract update in the same change.
- `redact.py` runs before any AI provider sees text (AGENTS.md rule 6). It is best-effort by design
  (decision 0240); the rule order is fixed, so read 0240-0244, 0255 and 0260-0262 before changing it
  (each names `redact.py` in its Where line). Property tests, not
  examples, guard "never leaks".
- Persisted identifiers (event ids, ledger fields) are permanent: deprecate, never rename.
- Public interface changed: update `docs/contracts/core.md` and `docs/MAP.md`, then `mise run gen:build`.
