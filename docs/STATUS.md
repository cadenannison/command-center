# Status

Where the work stands, so a fresh session does not re-derive it. Keep it under 50 lines. Update it when a
task ends: edit the lines, do not append a log. Decisions and their reasons live in `docs/decisions/`;
ideas not yet accepted live in `docs/backlog.md`. This file holds neither.

## Last updated
2026-11-10, HEAD `7d30913` (chore: raise test floor to 4446).

## In flight
Nothing. The working tree was clean at HEAD before the docs tidy (card D1); the redaction, provider,
rig and agent-cost work (decisions 0240-0258) and the chat fixes are all committed. Agents never commit
(AGENTS.md); the human reviews the diff and commits.

## Gate state
Seen on 2026-11-10: `mise run check:fast` passes (fmt:check, lint, typecheck, arch: 12 contracts kept,
0 broken); `mise run test:count` prints 4446 and `.test-floor` is 4446. No known red gates. The
intermittent redaction idempotence failure noted earlier has not been reproduced in this check; it
was not re-run in the full suite by card D1.

## Next
- Card G1: Gmail pending-connect wording (decisions 0190-0194).
- Then the UI redesign.
- Remaining backlog (`docs/backlog.md`): Postgres sync vs check-off deadlock retry (0233),
  `CHAT_TRUST_ENV` opt-in (0225), move the `base.html` error handler to a static file if a CSP is added
  (0212), pairing refresh-row purge, `GeminiIntegration.validate` catch-all, save chats,
  summary-provider unification, and the pytest-asyncio loop-scope setting (the human edits
  `pyproject.toml`). Also accepted: the city-name weather form.
- Run a layer agent (adapter-, services-, storage-, api-, web-engineer) on the next real task; none has
  been tried yet. Watch whether the under-200-word reports hold.
- Optional: the read-deny list in `.claude/settings.json` (`uv.lock`, `.venv`, caches); only the human
  edits that file. `api-reference.md` lists only method, path and summary, so parameters and schemas
  are only in `openapi.json` (grep it, never read it whole).

## Known quirks
- `guard-bash.sh` blocks a Bash command that merely contains words like "commit" after "git" (for
  example inside a heredoc of prose). Put such text in a file with the Write or Edit tool instead.
- A full `mise run check` once took over 10 minutes under load; the test stage alone is about 90 s.

## Reading order for a new task
1. `AGENTS.md` (loaded for you), then the `CLAUDE.md` in the directory you will edit, if there is one.
2. The one contract for that layer in `docs/contracts/`. Large file: `grep -n '^## '` it, then Read the
   section you need with offset and limit.
3. Find a file in `docs/generated/module-index.md`. Decisions behind it: grep its path in
   `docs/generated/decisions-by-file.md`, then the numbers in `docs/generated/decision-index.md`. Do not
   read either index whole.
4. Tests for a source file: `mise run test:for -- <src path>`.
