# 0332. Urgency is deterministic, explainable and computed in core with no AI

Status: accepted

Context: Needs me ranks items, and an expanded item answers "Why is this a 9?". The priority pill shows 1 to 10 on every task.
Decision: Urgency is a pure function in `src/command_center/core`: an item and a Clock in, a priority from 1 to 10 plus a list of reasons out, each reason carrying its points (for example "Due in 6 hours: +4"). The priority is derived from the sum of the points. No AI, no network and no randomness are involved. The API returns the priority and the reasons; the UI never computes either. The point values are defined in the task that builds it and recorded in docs/contracts/core.md.
Alternative: An AI-ranked list (rejected: not explainable or repeatable, and it would put the ranking behind an opt-in setting). Compute in the UI (rejected: a second copy of the rule that the phone app and an assistant would not share; core rule 1 keeps rules in core).
Reason: A person can check why an item ranks where it does, tests are exact, and the ranking works with every AI setting off (AGENTS.md rule 6).
Consequences: The same item and clock always give the same score. Reasons are data, so they must not carry email bodies or secrets. Changing point values changes visible numbers, so they are tested by example.
Where: not built yet; `core/` (a new module), exposed by an additive /v1 field (0302).
Revisit when: users ask to tune the weights, or a reason needs data core does not receive.
