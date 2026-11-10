# 0250. Agents get a status file and per-layer notes, not a longer root CLAUDE.md

Status: accepted

Context: A fresh agent session re-derived the repo state and the layer rules every time. The root files (`CLAUDE.md` + `AGENTS.md`, about 1.7k tokens) load every session, so growing them taxes every task, while `.claude/rules/` only carries rules, not a map of a layer.
Decision: (1) `docs/STATUS.md` (kept under 50 lines, edited in place, not a log) holds the in-flight work, the state of each gate and what is next. (2) Each layer directory under `src/command_center/` (core, services, adapters, storage, api, web, workers) has a short `CLAUDE.md`: its contract, the key files, the pitfalls, and pointers to decisions. It loads only when an agent works in that directory. (3) AGENTS.md gains a pointer to both and a rule to `grep -n '^## '` a large contract and read one section.
Alternative: Put the layer notes in the root `AGENTS.md` (rejected: loaded in every session for every task). Put them in `.claude/rules/` with `paths:` (rejected: that directory holds rules that apply to every file of a kind; the notes are per-layer orientation and name contract sections and decisions). One long STATUS log (rejected: it grows without bound; git history already is the log).
Reason: Cost scales with what is loaded, and loading by directory keeps the cost proportional to the task.
Consequences: The notes can go stale. They name contracts, files and decision numbers instead of repeating rules, so most changes do not touch them. A change to a layer's rules or key files updates its note in the same change. STATUS.md must be edited when a task ends; a stale STATUS is worse than none, so the Definition of done in AGENTS.md should name it if it is not kept up.
Where: `docs/STATUS.md`; `src/command_center/core/CLAUDE.md`, `src/command_center/services/CLAUDE.md`, `src/command_center/adapters/CLAUDE.md`, `src/command_center/storage/CLAUDE.md`, `src/command_center/api/CLAUDE.md`, `src/command_center/web/CLAUDE.md`, `src/command_center/workers/CLAUDE.md`; `AGENTS.md` (the read-order lines).
Revisit when: A layer note exceeds about 20 lines, STATUS.md is found stale twice, or a layer is added.
