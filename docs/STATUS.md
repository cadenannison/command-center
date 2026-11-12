# Status

Where the work stands, so a fresh session does not re-derive it. Keep it under 60 lines. Update it when a
task ends: edit the lines, do not append a log. Decisions and their reasons live in `docs/decisions/`;
ideas not yet accepted live in `docs/backlog.md`. This file holds neither.

## Last updated
2026-11-12.

## In flight
T1 (design tokens, themes and base components in `ui/`) is written and uncommitted, decisions 0340-0343 and 0345 (T1b: the pressed-button contrast bug was tailwind-merge dropping the on-fill color; a browserless contrast test, `ui/src/styles/contrast.test.ts`, its known-failures list is now empty after 0346 changed four tokens.json values to reach AA; prototype and spec keep the originals):
the real tokens in `ui/src/styles/tokens.css` (dark default, light, high contrast), display settings as
`<html>` attributes (`ui/src/lib/display.tsx`: contrast, density, glow 0 to 1.6, text scale 90 to 150),
self-hosted Sora, `.glass` and glow, AppBackdrop, Button, Card, Badge, Skeleton, Pill, SourceDot, and a
dev-only `/gallery`. Vitest: a drift test of tokens.css against `docs/design/tokens.json`, Pill and display
tests. Not run by the agent: `ui/e2e-gallery` (axe in dark, light and high contrast, and the Sora tnum
width check; run it with the dev server config `ui/playwright.gallery.config.ts`) and `ui/e2e` after the
restyle. Open for the human: `OFL-Sora.txt` was not in `docs/design/assets/`, so it is not yet in
`ui/public/fonts/` (the font license must travel with the font). Not yet an api task: the CSP header and
serving `ui/dist` with an SPA fallback from FastAPI.

## Gate state
`mise run test:count` prints 4894 and `.test-floor` is 4894. The Python gates pass. `ui:test:count` prints
168 (Vitest, `ui:fast` and the build pass; `ui/.test-floor` is still 33, the human raises it). Not yet shown by test: that `minimumReleaseAge`
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
