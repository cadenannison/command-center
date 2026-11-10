# api

Contract: `docs/contracts/api.md` (behaviour and reasons). For a route, parameter or schema, read the
generated `docs/generated/api-reference.md`, not the hand-written contract; if they disagree, the
generated one is right. Never read `docs/generated/openapi.json` whole. Rules that load here:
`.claude/rules/layers.md`, `style.md`, `tests.md`.

- Paths under `/v1`, parameters and schemas are permanent. `openapi.json` is the contract for a separate
  mobile repo, so any API change is a breaking-change decision: write a decision record first.
- Thin handlers: validate, call one service method, respond. Imports services and core; `factory.py` may
  also mount `web`. Never import adapters or storage.
- The settings API is write-only: return status (set + last4), never a value.
- After a route change run `mise run gen:build`, then `mise run gen:check`. Never hand-edit
  `docs/generated/`.
