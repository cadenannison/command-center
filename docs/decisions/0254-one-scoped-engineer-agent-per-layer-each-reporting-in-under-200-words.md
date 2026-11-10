# 0254. One scoped engineer agent per layer, each reporting in under 200 words

Status: accepted

Context: Only core had a scoped implementation agent (`domain-engineer`). Other layer tasks ran in the main session or a generic agent that could read and edit anything, and the reports back were unbounded.
Decision: Add `adapter-engineer`, `services-engineer`, `storage-engineer`, `api-engineer` and `web-engineer` in `.claude/agents/`, each on sonnet like `domain-engineer`. Each states the directories and docs it may edit, the contract and layer note it reads, "stop and report a change outside the scope", test-first, no commit or push, `mise run check` before done, and a report of files changed, contract changes, tests run and open issues in under 200 words. `api-engineer` stops before any change to a `/v1` path, parameter or schema. All of them list a judgement call in the report when they have no decision number.
Alternative: One generic engineer agent that is told the layer in the prompt (rejected: the scope is then only as good as each prompt). Give agents numbers from a range (rejected: the numbers belong to the project manager, docs/decisions/README.md).
Reason: A narrow scope keeps an agent from reading other layers, and a bounded report keeps the main session thin.
Consequences: Six agent files to keep in step with AGENTS.md; they restate no rule that is not already there, only the scope.
Where: `.claude/agents/adapter-engineer.md`, `.claude/agents/services-engineer.md`, `.claude/agents/storage-engineer.md`, `.claude/agents/api-engineer.md`, `.claude/agents/web-engineer.md`, `.claude/agents/domain-engineer.md`; `CLAUDE.md` (the "Slice work" line).
Revisit when: A layer is added or split, or an agent keeps hitting its scope limit.
