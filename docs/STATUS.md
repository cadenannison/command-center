# Status

Where the work stands, so a fresh session does not re-derive it. Keep it under 60 lines. Update it when a
task ends: edit the lines, do not append a log. Decisions and their reasons live in `docs/decisions/`;
ideas not yet accepted live in `docs/backlog.md`. This file holds neither.

## Last updated
2026-11-10, HEAD `4779a5a` (docs: refresh STATUS.md, decision ranges and backlog notes), plus the
uncommitted work below (card D2).

## In flight
In the working tree, not committed: the redaction work (R3, decisions 0280-0284, `core/redact.py`),
the chat key-shape work (C5, decisions 0290-0292, `core/chat.py`, `services/chat_settings.py`, the chat
panel) and the tooling fixes (T1, decisions 0285-0289: `test:for`, the decision-by-file index, the
stop gate, the Ollama summary cap), with their tests and the docs for them. Other sessions may still be
editing `core/chat.py` and `tests/test_chat_key_shapes.py`. Agents never commit (AGENTS.md); the human
reviews the diff and commits.

## Gate state
Seen on 2026-11-10 in the working tree: `mise run check:fast` FAILS on lint: E501 (line 104 > 100) at
`tests/test_chat_key_shapes.py:4`, a file another session is editing, so it was not touched here.
`fmt:check` (609 files formatted), `typecheck` (0 errors) and `arch` (12 contracts kept, 0 broken) pass
when run alone. `mise run test:count` prints 4856; `.test-floor` is 4446 (raise it when the work is
committed). The full test suite was not run by card D2. The intermittent redaction idempotence failure
noted earlier has not been reproduced.

## Next
- Commit the redact, chat and tooling work now in the working tree (after the lint error above is fixed
  and `mise run check` passes).
- Then card G1: Gmail pending-connect wording (decisions 0190-0194).
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
