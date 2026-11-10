# Status

Where the work stands, so a fresh session does not re-derive it. Keep it under 50 lines. Update it when a
task ends: edit the lines, do not append a log. Decisions and their reasons live in `docs/decisions/`;
ideas not yet accepted live in `docs/backlog.md`. This file holds neither.

## Last updated
2026-11-10, HEAD `222e82f` (feat: chat page and AI provider settings).

## In flight (uncommitted in the working tree)
- Redaction hardening: `core/redact.py` and its tests (decisions 0240-0244, 0255).
- Provider and outbound-path hardening: summary providers, city search, chat (decisions 0245, 0246).
- Test rigs and guards: schema guard, auth rig, context preview (decisions 0247-0249).
- Agent-cost aids: this file, the `CLAUDE.md` in each layer, `docs/generated/module-index.md` and
  `decisions-by-file.md`, `mise run test:for`, the fingerprint in `scripts/hooks/stop-gate.sh`, and the
  `*-engineer` agents in `.claude/agents/` (decisions 0250-0254).
- Chat fixes from the C2 review (task C3, decisions 0256-0258): opt-ins the page showed are checked on
  send, one 120 s deadline covers the lock wait and the provider call, key-shaped model names and
  addresses are refused by the redaction rule. Open: `tests/test_redact_gaps.py` idempotence property
  test fails intermittently in the full run (passes alone); it belongs to the redaction work.
- The human reviews the diff and commits. Agents never commit (AGENTS.md).

## Gate state (last full `mise run check`)
| Gate | State |
|---|---|
| `fmt:check`, `lint`, `typecheck`, `arch`, `gen:check`, `audit`, `secrets` | pass |
| `test` | 2 failures, both Hypothesis cases in the redaction tests: `tests/test_redact.py::test_redact_replaces_any_separator_joined_number_of_six_or_more_digits` (`x 0.0.0.0 y`: the test says fewer than 6 digits stay as written, decision 0244 masks every address as `[ip]`) and `tests/test_redact_gaps.py::test_redact_is_idempotent_on_text_built_from_the_new_rules_pieces` (`02026-11-09www.code `: the number mask leaves `]` before `www.code`, so a second pass masks it as `[url]`). Both need a decision; the six-digit `x 0 0 [ip] y` case is fixed by 0255. |

## Next
- Decision 0255 (filed): the IPv4 rule runs after the digit-group rule; it amends 0240's rule order.
- Settle the two redaction test failures above (test change for the first, bare-URL lookbehind or rule order for the second).
- Run a layer agent (adapter-, services-, storage-, api-, web-engineer) on the next real task; none has
  been tried yet. Watch whether the under-200-word reports hold.
- Optional: the read-deny list in `.claude/settings.json` (`uv.lock`, `.venv`, caches); only the human
  edits that file. Keep `docs/generated/openapi.json` readable: `api-reference.md` lists only method,
  path and summary, so parameters and schemas are only in `openapi.json`.
- Backlog items marked `accepted`: see `docs/backlog.md` (city-name weather form).

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
