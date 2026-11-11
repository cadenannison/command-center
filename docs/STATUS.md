# Status

Where the work stands, so a fresh session does not re-derive it. Keep it under 60 lines. Update it when a
task ends: edit the lines, do not append a log. Decisions and their reasons live in `docs/decisions/`;
ideas not yet accepted live in `docs/backlog.md`. This file holds neither.

## Last updated
2026-11-11.

## In flight
P1a (the `ui/` skeleton) is in progress and uncommitted: `ui/package.json` (no dependencies, pnpm 12.14.0
pinned), `tsconfig.json`, `vite.config.ts`, `vitest.config.ts`, `eslint.config.js`, `index.html`, and
decisions 0315 and 0316. No source code yet; P1b writes it. K1, K1b, H1 and H2 are committed (the UI
decisions 0300-0304, the UI guard and CI job, the `ui:*` mise tasks, the redact timing budget 0310).
Agents may not write `ui/pnpm-workspace.yaml`, the lockfile or `mise.toml`, so these wait on the human, in
`$TMPDIR/p1a-guard.patch` (`git apply` it): the `pnpm = "12.14.0"` pin in `mise.toml`,
`ui/pnpm-workspace.yaml` (the supply-chain settings; pnpm 12 ignores them in `.npmrc`, decision 0315) and a
Dependabot entry for `/ui`. Still needed after that: `ui/pnpm-lock.yaml` (the guard requires it) and the
approved dev dependencies installed with the frozen flags. Until then `mise run check:fast` fails in its
`ui:fast` step (decision 0316). The guard does not read the lockfile contents (0301).

## Gate state
`mise run test:count` prints 4894 and `.test-floor` is 4894. The Python gates pass. `ui:fast` fails until
the human steps above are done. Not yet shown by test: that `minimumReleaseAge` rejects a too-new
version and that `strictDepBuilds` fails an unreviewed build script (0315 Hedge).

## Next
- The human applies `p1a-guard.patch`, creates the lockfile and installs; then P1b: the source files, the
  `ui:test:count` parse, `ui/.test-floor`, the generated client (an OpenAPI generator needs approval with
  registry facts), the CSP header (an api task). Then port the widgets one by one, each with its /v1
  endpoint (0302).
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
  example inside a heredoc of prose), and any command that mentions `pnpm` next to "install". Put such
  text in a file with the Write or Edit tool instead.
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
4. Tests for a source file: `mise run test:for -- src/command_center/core/redact.py`.
