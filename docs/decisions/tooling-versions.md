# Tooling versions and resolved (verify) items

Checked 2026-11-07. Re-check before bumping; pins live in `mise.toml`, `pyproject.toml` and `uv.lock`.

## Pinned tools (mise registry confirmed each exists)
| Tool | Pin | Note |
|---|---|---|
| python | 3.13.18 | kit's 3.13; all dependencies support >=3.11 |
| uv | 0.13.7 | `uv_build` backend pinned `>=0.13.7,<0.14` to match |
| node | 26.13.0 | only for the pyright wrapper (see 0009) |
| gitleaks | 8.30.1 | `gitleaks git --redact` ran clean on this version |

## Dependencies
All 25 declared packages (runtime, extras, dev) resolved on PyPI; `uv.lock` pins 129 packages. Lower bounds
in pyproject.toml are the versions seen on the registry that day. Observations:
- `fastapi 0.162.2` was published the same day it was locked (a fresh release). `uv.lock` pins it; Dependabot
  is set to a 7-day cooldown for later bumps.
- `rumps 0.4.0` was last released in 2022 (no Python constraint declared) and is macOS-only; it is isolated to
  the `desktop` extra and one adapter file. `qrcode 8.2` is from 2025-05. `httpx 0.28.1` is from 2024-12.
- `caldav` pulls in transitive packages worth a look when the CalDAV adapter is built (`urllib3-future`, `wassima`).
- `import-linter 2.16` requires Python >=3.11 and fails a config with no contracts (ours has 12).
- `ty` was not used; pyright chosen (0009).

## GitHub Actions (pinned to full SHAs; all three run on Node 24)
| Action | Tag | SHA |
|---|---|---|
| actions/checkout | v7.0.1 | 3d3c42e5aac5ba805825da76410c181273ba90b1 |
| jdx/mise-action | v5.2.7 | b44d12e7d0d8ee7461bb893e1b1993500433185b |
| actions/dependency-review-action | v5.0.0 | a1d282b36b6f3519aa1f3fc636f609c47dddb294 |

The tags are lightweight (not annotated), so the SHAs from `git ls-remote` are the target revisions themselves.

## (verify) items from the kit
| Item | Result |
|---|---|
| `sandbox.enabled`, `failIfUnavailable`, `allowUnsandboxedCommands`, `filesystem.denyRead`, `network.allowedDomains` | exist (sandboxing docs) |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | exists; whole tokens 100000-1000000 (250000 valid) |
| `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` | exists; default is 3, `1` turns nesting off, as intended |
| `stop_hook_active` in Stop hook input | exists; true when already continuing from a stop hook |
| Subagent frontmatter `maxTurns`, `omitClaudeMd` | exist (omitClaudeMd needs v2.1.271+); new agent files hot-reload (the first file in a new `agents` dir needs a restart) |
| Dependabot `uv` ecosystem and `cooldown.default-days` | supported |
| `test:count` output format | `pytest --collect-only -q` ends "N tests collected in Xs"; the task extracts N (a digits-only parse of that line would give N plus the time digits) |
| gitleaks flags | `gitleaks git --redact` verified by running it; `--pre-commit --staged` not exercised (nothing staged) |
| `pip-audit` flags | `--local --skip-editable`; runs clean after the `.pem` rule change (see Deviations) |
| mutmut config keys | `paths_to_mutate`, `tests_dir`; `mise run mutate` NOT run yet (core is nearly empty) |

## Deviations from the kit's `.claude/settings.json` (python-uv profile), 2026-11-07
`permissions.deny` Read and Edit rules are merged into the Bash sandbox's deny lists (sandboxing docs), so a rule
meant to keep files out of the agent's context also blocks the project's own tooling when it runs in the
sandbox. Three kit rules were changed on the repo owner's instruction:

| Kit rule | Change | Reason |
|---|---|---|
| `Read(./**/.venv/**)` | removed | Blocked uv from reading the project virtualenv, so every `uv run` / `mise run` task failed in the sandbox. |
| `Edit(./docs/generated/**)` | removed | Made `docs/generated/` unwritable in the sandbox, so `mise run gen:build` (which AGENTS.md tells agents to run) failed. `gen:check` and the reviewer still catch hand edits; AGENTS.md still says never hand-edit. |
| `Read(//**/*.pem)` | replaced with `Read(./*.pem)` | The absolute-path rule blocked certifi's `cacert.pem`, which httpx, requests and pip-audit load for HTTPS (`mise run audit` failed). `./*.pem` still protects key files in the repo root. |

Pattern check: Read and Edit rules use gitignore syntax; `./path` is relative to the current directory and `*`
matches within a single path segment (permissions docs). So `Read(./*.pem)` is valid, but it matches only `.pem`
files in the project root, not nested ones such as `keys/server.pem`. Add `Read(./**/*.pem)` only if such a
directory appears, and note that it would also match certifi inside any in-repo `.venv`.
Verified after the change: `gen:build`, `gen:check` and `audit` pass in the sandbox.

### Resolved: recursive build-directory rules matched inside `.venv`
`Read(./**/dist/**)` blocked pyright's own `.venv/lib/python3.13/site-packages/pyright/dist/index.js`, so
`typecheck` (and therefore `check:fast` and the Stop hook) failed in the sandbox. `**` also matches inside `.venv`,
so the same would hit any package that ships a `dist/`, `target/` or `node_modules/` directory. Changed on the
repo owner's instruction, anchoring each rule to the project root:

| Kit rule | Change | Note |
|---|---|---|
| `Read(./**/dist/**)` | `Read(./dist/**)` | root `dist/` only |
| `Read(./**/node_modules/**)` | `Read(./node_modules/**)` | root `node_modules/` only; this repo has no JS packages |
| `Read(./**/target/**)` | none needed | this rule was never in this repo's settings.json (Rust-only entry, omitted at bootstrap); if added later, use `Read(./target/**)` |

Trade-off: a nested `dist/` or `node_modules/` (for example `web/dist/`) is no longer hidden from agents' reads.
