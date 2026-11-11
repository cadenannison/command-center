# Status

Where the work stands, so a fresh session does not re-derive it. Keep it under 60 lines. Update it when a
task ends: edit the lines, do not append a log. Decisions and their reasons live in `docs/decisions/`;
ideas not yet accepted live in `docs/backlog.md`. This file holds neither.

## Last updated
2026-11-11.

## In flight
No task is in progress. Uncommitted in the working tree, for the human to review and commit: the K1 and
K1b docs (decisions 0300-0304, `docs/approved-dependencies.md`, the UI agents, backlog items, README table,
generated indexes) and H2 (decision 0310, `tests/test_redact_gaps.py`). There is no `ui/` directory yet.
The guard and rule changes for the UI are a patch at `$TMPDIR/k1-guard.patch` (AGENTS.md,
`docs/standards.md`, CI `ui` job, `mise.toml` `ui:*` tasks, `scripts/ui.sh`, `scripts/hooks/guard-bash.sh`,
`.gitleaks.toml`, `.claude/settings.json`, CODEOWNERS, PR template). Until it is applied, AGENTS.md still
says the UI is Jinja + HTMX. One known gap in it: the guard does not read `ui/pnpm-lock.yaml` (0301).

## Gate state
`mise run test:count` prints 4894. `.test-floor` is 4856 in the working tree; the human raises it to 4894
with the commit. `mise run check:fast` passes. The intermittent redaction idempotence failure noted
earlier has not been reproduced.

## Next
- The human applies the K1 guard patch (`git apply`) and commits it as its own commit.
- P1: scaffold `ui/` (decisions 0300-0304): the lockfile guard check, the pnpm pin, `ui:test:count`,
  `minimumReleaseAge` tested, Dependabot for `ui/`, the generated client, the CSP header (an api task),
  `ui/.test-floor`. Then port the widgets one by one, each with its /v1 endpoint (0302).
- Design after P1.
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
