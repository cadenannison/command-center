# Status

Where the work stands, so a fresh session does not re-derive it. Keep it under 60 lines. Update it when a
task ends: edit the lines, do not append a log. Decisions and their reasons live in `docs/decisions/`;
ideas not yet accepted live in `docs/backlog.md`. This file holds neither.

## Last updated
2026-11-13.

## In flight
T1 (tokens, themes, base components, dev-only `/gallery`) and R1 (layout model) are committed. Not run by the
agent: `ui/e2e-gallery` (config `ui/playwright.gallery.config.ts`) and `ui/e2e`. Open for the human:
`OFL-Sora.txt` is not in `docs/design/assets/`. Not yet an api task: the CSP header and serving `ui/dist`
with an SPA fallback from FastAPI.

R2 and R2b (dashboards routes, 0355-0358) are committed. Postgres runs of `test_dashboard_store.py` need
CC_TEST_POSTGRES_URL (the human). E2a (0389) adds `zoom` and `shortcuts` to the display settings (uncommitted).

R3 (the /dashboard grid in `ui/src/features/dashboard/`, decisions 0360-0363) is written and uncommitted:
tabs, grid, widget shell with its states, edit mode (pointer and keyboard, 12 columns only), debounced
If-Match saving. Not run by the agent: `ui/e2e/dashboard.spec.ts` and anything in a real browser (CSSOM
styles under the CSP, touch drag, a screen reader). Tasks (0373), Week (0377) and Weather (0376) widgets are
built; other kinds are still placeholders. Events (0378) is on the grid too; the Summary card (0381, 0382) is pinned above it, not a grid widget. A failed dashboards refetch keeps the grid and edits (0375).
Weather shows high, low and outlook only: current conditions and hours need a backend card (0376).
Not run by the agent: `ui/e2e/dashboard-widgets.spec.ts`, `dashboard-events.spec.ts` and `dashboard-summary.spec.ts` (need a browser).
E1 (edit tools, 0383-0384) is uncommitted; undo and redo shortcuts wait for a setting. Not run: `ui/e2e/dashboard-edit.spec.ts`; Radix under the CSP (0383).
U6a (`GET /v1/needs-me`, 0385-0386) is committed; U6b (the Needs me widget, 0387; a stale delayed live-region announcement fixed, 0388) is uncommitted. Not run: `ui/e2e/dashboard-needs-me.spec.ts`. The other e2e specs that show the default layout do not stub `/v1/needs-me` yet (the human or a card adds it).

## Gate state
`mise run test:count` prints 5107; `.test-floor` is 4894 (the human raises it). The Python gates pass. `ui:test:count` prints
720 (`ui:check` passes with the build; `ui/.test-floor` is 683, the human raises it). Not yet shown by test: that `minimumReleaseAge`
rejects a too-new version, that `strictDepBuilds` fails an unreviewed build script (0315 Hedge), and the Playwright test.

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
