# Status

Where the work stands, so a fresh session does not re-derive it. Keep it under 60 lines. Update it when a
task ends: edit the lines, do not append a log. Decisions and their reasons live in `docs/decisions/`;
ideas not yet accepted live in `docs/backlog.md`. This file holds neither.

## Last updated
2026-11-11.

## In flight
P1b (UI scaffold, plumbing only) is written and uncommitted: `ui/src` (app shell, TanStack Query and Router,
`/today` through the typed client with loading, empty, error and stale states, tokens and a light, dark and
system switcher, Button, Card, Badge, Skeleton), `ui/e2e` and `ui/playwright.config.ts` (smoke test with axe,
not run: no browser installed), `mise run ui:gen`, decisions 0320-0324. P1a is committed. It is BLOCKED on
the human by decision 0324: the locked `typescript@7.0.2` breaks eslint (typescript-eslint) and the client
generator (openapi-typescript needs the TS 5 compiler API), so `ui:fast` fails and
`ui/src/api/generated/schema.d.ts` does not exist (typecheck fails on that one import). Human steps: set
`typescript` to `5.9.3` in `ui/package.json` and re-lock; `git apply $TMPDIR/p1b-guard.patch` (lockfile
check, `gen-check`, Playwright CI steps, mise tasks); `mise run ui:gen`; create `ui/.test-floor` with the
count `mise run ui:test:count` prints; install the Playwright browser; then `mise run ui:check`. Not yet an
api task: the CSP header and serving `ui/dist` with an SPA fallback from FastAPI.

## Gate state
`mise run test:count` prints 4894 and `.test-floor` is 4894. The Python gates pass. `ui:test:count` prints
33 (Vitest passes; build passes); `ui:fast` fails (0324). Not yet shown by test: that `minimumReleaseAge`
rejects a too-new version, that `strictDepBuilds` fails an unreviewed build script (0315 Hedge), and the
Playwright test.

## Next
- The human unblocks P1b (above); then the CSP header and static serving (api task), then port the widgets
  one by one, each with its /v1 endpoint (0302).
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
