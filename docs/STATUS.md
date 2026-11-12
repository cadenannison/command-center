# Status

Where the work stands, so a fresh session does not re-derive it. Keep it under 60 lines. Update it when a
task ends: edit the lines, do not append a log. Decisions and their reasons live in `docs/decisions/`;
ideas not yet accepted live in `docs/backlog.md`. This file holds neither.

## Last updated
2026-11-12.

## In flight
T1 (design tokens, themes, base components in `ui/`, decisions 0340-0343, 0345, 0346) is written and
uncommitted: tokens in `ui/src/styles/tokens.css`, display settings as `<html>` attributes
(`ui/src/lib/display.tsx`), self-hosted Sora, `.glass`, base components, a dev-only `/gallery`. Not run by the
agent: `ui/e2e-gallery` (axe in three themes, Sora tnum width; config `ui/playwright.gallery.config.ts`) and
`ui/e2e`. Open for the human: `OFL-Sora.txt` is not in `docs/design/assets/`, so not in `ui/public/fonts/`.
Not yet an api task: the CSP header and serving `ui/dist` with an SPA fallback from FastAPI.

R1 (widget registry and layout model, `ui/src/layout/`, decision 0350) is written and uncommitted. Nothing
renders it yet. Open for the edit-mode UI task: edit only at 12 columns (0350 Consequences).

R2 and R2b (dashboards and display settings behind /v1, decisions 0355-0358) are written and uncommitted:
core validation, two tables with compare-and-set revisions, `api/dashboards.py`, typed client regenerated.
Postgres runs of `test_dashboard_store.py` need CC_TEST_POSTGRES_URL (the human). The ui layer does not call
these routes yet.

## Gate state
`mise run test:count` prints 5004; `.test-floor` is 4894 (the human raises it). The Python gates pass. `ui:test:count` prints
304 (Vitest and `ui:fast` pass; the build was last run at 168 tests; `ui/.test-floor` is still 33, the human raises it). Not yet shown by test: that `minimumReleaseAge`
rejects a too-new version, that `strictDepBuilds` fails an unreviewed build script (0315 Hedge), and the
Playwright test.

## Next
- The human unblocks P1b (above); then the CSP header and static serving (api task), then port the widgets
  one by one, each with its /v1 endpoint (0302).
- Design reference is in `docs/design/` (D1, decisions 0330-0336, uncommitted): read `design/README.md`, then the spec section a task implements. Widgets come after the P1b unblock.
- Remaining backlog (`docs/backlog.md`): Postgres sync vs check-off deadlock retry (0233),
  `CHAT_TRUST_ENV` opt-in (0225), move the `base.html` error handler to a static file if a CSP is added
  (0212), pairing refresh-row purge, `GeminiIntegration.validate` catch-all, save chats,
  summary-provider unification, the schema-guard runtime check, splitting `core/redact.py` into rule
  modules (0280), a `test:for` flag that prints every indirect test (0285), and the pytest-asyncio
  loop-scope setting (the human edits `pyproject.toml`). Also accepted: the city-name weather form.
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
2. The one contract for that layer in `docs/contracts/` (`grep -n '^## '`, then Read a section).
3. Find a file or its decisions through `docs/generated/` (grep, never read an index whole); tests for a
   source file: `mise run test:for -- <path>`.
