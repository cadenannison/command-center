# Command Center repo rules

## What this is
Personal productivity dashboard: aggregates calendars, Canvas, email and weather into day/week/month
views with an opt-in AI summary. Python 3.13, uv, FastAPI, Jinja2 + HTMX, SQLite by default.
Layout and import boundaries: docs/MAP.md. Patterns: docs/standards.md. Decisions and their reasons:
docs/decisions/. Read the one contract you need (docs/contracts/core.md, services.md, adapters.md,
storage.md, api.md), not the whole docs tree.
Current state, gate status and what is next: docs/STATUS.md. A layer directory under src/command_center
may hold its own CLAUDE.md (contract, key files, pitfalls); it loads when you work there.
Find a file: docs/generated/module-index.md (one line per module). Find the decisions behind a file:
grep its path in docs/generated/decisions-by-file.md, then look the numbers up in decision-index.md.
Large files: `grep -n '^## '` a contract and Read one section with offset and limit. Never read
docs/generated/decision-index.md or docs/generated/openapi.json whole; grep the index by keyword.

## Commands (same names in every repo; defined in mise.toml)
- mise run check          every non-mutating gate; run before saying a task is done
- mise run check:fast     fmt:check + lint + typecheck + arch
- mise run fix            autofix format and lint
- mise run fmt:check | lint | typecheck | test | arch | gen:check | audit | secrets
- mise run gen:build      regenerate docs/generated/ (openapi.json, api-reference.md) from the code
- mise run mutate         mutation testing on src/command_center/core (by hand; no CI workflow yet)
To run one test file: `uv run pytest tests/test_smoke.py --no-cov`. To find the tests that import a
source file: `mise run test:for -- src/command_center/core/redact.py` (direct imports only; the full
`mise run check` still decides done). Run `mise run setup` after every clone.

## Architecture rules (never break)
Rules 1-4 are enforced today by ruff banned-api and import-linter (pyproject.toml). Rules 5-6 are
enforced by tests that arrive with the features; until then they bind you by review.
1. src/command_center/core is pure: no I/O, clock, randomness, environment or globals. Time,
   randomness and ids come in as parameters (Clock, Rng, IdSource in core/ports.py). core imports
   nothing in the app and none of httpx, sqlalchemy, fastapi, keyring.
2. services depend on ports (Protocols in core/ports.py) only. adapters and storage import core only.
   api, web, desktop, workers and pairing import services and core, never adapters or storage. Only the
   composition roots build concrete infrastructure: src/command_center/app.py,
   src/command_center/workers/__main__.py, src/command_center/desktop/main.py.
3. Import direction follows docs/MAP.md. `mise run arch` fails the build on a violation.
4. Each vendor SDK is imported in exactly one adapter file (caldav, googleapiclient/google_auth_oauthlib,
   google-genai, keyring, redis, rumps). The contract names the file in pyproject.toml.
5. Secrets live in the OS keychain through keyring. The settings API is write-only (status = set +
   last4). The server binds 127.0.0.1. Nothing secret is logged, committed or put in a URL.
6. AI summaries are opt-in and OFF by default. Redaction (in core) runs before any provider sees data:
   titles, due dates and trimmed subjects only, addresses and numbers stripped, never email bodies.
Reuse the shared building blocks in docs/contracts/core.md; do not invent a parallel shape.

## Generated files (never hand-edit)
Everything under docs/generated/ comes from `mise run gen:build`. Change the source, rebuild, and run
`mise run gen:check`. For a route, parameter or schema, read the generated page, not the hand-written
contract; contracts hold behaviour and reasons. If the two disagree, the generated one is right.
openapi.json is the contract for a separate mobile repo, so an API change is a breaking-change decision.

## Working style
- One small vertical change per task, in one module where possible.
- Behaviour change: write the failing test first, then implement until it passes.
- Never edit, delete, skip or weaken an existing test to make it pass. If a test looks wrong, stop and
  report why. Tests change only when the task card says `tests: modify`.
- If a task is impossible or underspecified, say so and stop. Do not special-case, stub or fake a
  result to satisfy a check.
- Fix root causes. Never re-run an identical failing command: read the error or logs, change
  something, then retry. Any retry loop you write needs a failure class, a cap, backoff and a logged reason.
- All dependencies are already declared in pyproject.toml and locked in uv.lock; do not edit either.
  A new dependency needs asking first, and the name must be verified on PyPI (age, downloads, repo)
  because models invent plausible package names.
- Never run git commit, git push or any destructive git command (stash, clean, rebase, restore,
  checkout --, reset --hard, --no-verify). To compare with HEAD use `git show HEAD:path`. When a task
  is done, stop and report what changed; the human reviews the diff and commits.
- Stop and ask ONLY for: a genuine design ambiguity (name the question, give a recommendation and
  tradeoffs), a new dependency, or a missing/unclear contract. Fix bugs, test failures and mechanical
  review findings without asking.
- Record every judgement call, deviation from a task card, or choice between real alternatives as a
  new numbered file in docs/decisions/: the decision, the alternative not taken, why, where it lives
  in code, and when to revisit it. To change a decision, write a new record that supersedes the old
  one. An old record may be edited in place only on its Status line and its Sources line.
- Never log or commit secrets, tokens, PII or seeds. Read config from the environment or keyring.
  Invented test credentials must start with "fake-" (the only value .gitleaks.toml allowlists).
- Read the package's contract instead of its source when you are not editing it. Update the contract
  in the same change if you alter a public interface.
- Identifiers that are persisted or referenced elsewhere (DB columns, API paths under /v1, settings
  keys) are permanent: deprecate, never rename or delete.
- Never edit tests with scripts or shell commands to get around guard-tests; if the hook blocks an edit, stop and report.
- Don't read the real database under ~/.command-center unless the project manager asks; if told to, print only counts and types, never titles, links or notes.

## Definition of done
`mise run check` passes · a test exists that fails without the change · contracts/MAP updated if an
interface changed · `gen:build` run and `gen:check` clean · reviewer found nothing needing a decision
(max 2 fix rounds, then escalate) · STOP and report. The human commits.
