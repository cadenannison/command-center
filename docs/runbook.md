# Runbook

## Run locally
1. `mise install && mise run setup` (installs pinned tools, git hooks and dependencies).
2. `uv run command-center` serves the API on http://127.0.0.1:8765 (health: `/v1/health`).
3. Needs `jq` on PATH for the agent guard hooks (`brew install jq`).

## Common situations (fill in as features land)
- Gmail shows "Reconnect": the refresh token expired (7 days while the OAuth client is unverified).
  Reconnect from settings. See docs/decisions/0003-gmail.md.
- Phone cannot connect: the Mac is asleep, or Tailscale Serve is off. Never use Funnel.
- Rotate a secret: overwrite it through the settings API (write-only); the old value is replaced in the keychain.

## Production-readiness checklist (local-first app; tick before relying on it daily)
- [ ] `mise run check` green on main; CI `gate` job is the only required status check
- [ ] Server bound to 127.0.0.1 only; no 0.0.0.0 anywhere
- [ ] Every secret in the keychain; settings API write-only; `mise run secrets` clean
- [ ] Summaries OFF by default; redaction property-tested; email excluded unless opted in
- [ ] Every outbound call has a timeout; every source shows per-source health in the UI
- [ ] Backup/restore of the SQLite file tested; schema migrations tested on a copy
- [ ] `docs/generated/openapi.json` current; breaking /v1 changes have a decision record
- [ ] Dependency audit reviewed (weekly CI job); Dependabot PRs not older than a month
