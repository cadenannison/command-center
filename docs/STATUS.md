# Status

Where the work stands, so a fresh session does not re-derive it. Keep it under 60 lines. Update it when a
task ends: edit the lines, do not append a log. Decisions and their reasons live in `docs/decisions/`;
ideas not yet accepted live in `docs/backlog.md`. This file holds neither.

## Last updated
2026-11-10, HEAD `3a2dda6` (chore: raise test floor to 4856), plus the uncommitted card G1 changes below.

## In flight
Nothing apart from card G1 (Gmail pending-connect wording), in the working tree and not committed:
decisions 0190-0192 (0193-0194 unused, reserved gaps), `web/sources.py`, `web/cards.py`,
`web/howto.py`, `web/templates/_card.html`, `_syncing_note.html`, `_status_fragment.html`, `tests/test_web_gmail_card.py` (20 new tests), `tests/test_secret_storage_wording.py` (18 new tests; the "stored only on this computer"
wording in `settings.html`, the chat how-to, README, SECURITY.md and docs, decision 0192), and the docs
for them (`docs/contracts/web.md`, `gmail-setup.md`, `sources.md`, `first-run.md`, `runbook.md`, the
regenerated decision indexes). Agents never commit (AGENTS.md); the human reviews the diff and commits.

## Gate state
Seen on 2026-11-10 in the working tree: `mise run check:fast` passes, `gen:check` is clean, and the full
`mise run test` passes (4757 passed, 137 skipped, coverage 94%). `mise run test:count` prints 4894;
`.test-floor` is 4856 (raise it to 4894 when G1 is committed). The intermittent redaction idempotence
failure noted earlier has not been reproduced.

## Next
- Commit card G1 (raise `.test-floor` to 4894 with it).
- Then the UI redesign.
- Remaining backlog (`docs/backlog.md`): Postgres sync vs check-off deadlock retry (0233),
  `CHAT_TRUST_ENV` opt-in (0225), move the `base.html` error handler to a static file if a CSP is added
  (0212), pairing refresh-row purge, `GeminiIntegration.validate` catch-all, save chats,
  summary-provider unification, the schema-guard runtime check, splitting `core/redact.py` into rule
  modules (0280), a `test:for` flag that prints every indirect test (0285), and the pytest-asyncio
  loop-scope setting (the human edits `pyproject.toml`). Also accepted: the city-name weather form.
- Run a layer agent (adapter-, services-, storage-, api-, web-engineer) on the next real task; none has
  been tried yet. Watch whether the under-200-word reports hold.
- Optional: the read-deny list in `.claude/settings.json` (`uv.lock`, `.venv`, caches); only the human
  edits that file. `api-reference.md` lists only method, path and summary, so parameters and schemas
  are only in `openapi.json` (grep it, never read it whole).

## Known quirks
- `guard-bash.sh` blocks a Bash command that merely contains words like "commit" after "git" (for
  example inside a heredoc of prose). Put such text in a file with the Write or Edit tool instead.
- Untracked scratch files in `src/`, `tests/` or `docs/` can change `gen:check` locally only (0287).
- `test:for` prints at most 15 "(indirect)" tests, then "+N more" (decision 0285); it cannot list the rest.
- A full `mise run check` once took over 10 minutes under load; the test stage alone is about 90 s.

## Reading order for a new task
1. `AGENTS.md` (loaded for you), then the `CLAUDE.md` in the directory you will edit, if there is one.
2. The one contract for that layer in `docs/contracts/`. Large file: `grep -n '^## '` it, then Read the
   section you need with offset and limit.
3. Find a file in `docs/generated/module-index.md`. Decisions behind it: grep its path in
   `docs/generated/decisions-by-file.md`, then the numbers in `docs/generated/decision-index.md`. Do not
   read either index whole.
4. Tests for a source file: `mise run test:for -- <src path>`.
