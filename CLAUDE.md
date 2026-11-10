@AGENTS.md

## Claude Code specifics
- Default model is sonnet (pinned in .claude/settings.json). Cheap subagents run haiku; the reviewer
  runs opus. Do not switch models mid-task: it throws away the prompt cache.
- Delegate: test-runner after changes; reviewer once per phase, with `git diff` pasted into its prompt.
- Slice work: the layer's own agent (domain-engineer for core; adapter-, services-, storage-, api-,
  web-engineer). Each is scoped to its directory and reports in under 200 words.
- Cross-module work: plan in a separate session and write the plan into the task card, then execute.
- Launch `claude` from the repo root; hook paths depend on it.

## Compact instructions
When compacting, keep: the task goal, files changed so far, any failing check and its output, and any
open decision the user has not answered. Drop restated docs; they are on disk.
