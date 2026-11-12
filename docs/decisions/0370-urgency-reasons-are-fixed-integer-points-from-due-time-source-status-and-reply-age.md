# 0370. Urgency reasons are fixed integer points from due time, source, status and reply age

Status: accepted

Context: Decision 0332 asks for a 1-10 priority with reasons. The existing `scoring.urgency` (0-100, decisions 0110 and earlier) has one text per score and feeds the attention list; it cannot say "+4 for this, +1 for that".
Decision: `core/urgency.py` `assess(event, now)` returns `priority` (the score clamped to 1-10), `score` (the sum of the reasons' points before the clamp) and `reasons` (`code`, `points`, one plain sentence). Inputs, all fields that already exist: `kind`, `source`, `status` (`done`, `owed`, `overdue`), `due`, `start` (the time of the last message, so the owed-reply age), `end`, and the `now` passed in. Weights: overdue +8, and +1 more when two days or more late; due within 6 h +7, 24 h +6, 48 h +5 ("soon"), 7 days +3, 14 days +1, later nothing; a task you added yourself (source `local`, kind `task`) +1; a reply owed +3, overdue +5, plus +1 when waiting 24 h or more or +2 for 72 h or more; an event in progress or starting within 2 h +4, within 24 h +2; done: one reason worth 0, priority 1. With no reason the list holds one 0-point "Nothing makes this urgent right now". Estimated duration and AI estimates are not inputs.
Alternative: Reuse `scoring.urgency` divided by 10 (rejected: no per-reason points). Make overdue grow without bound (rejected: the clamp hides it and it needs a cap to be explained).
Reason: Overdue (8) is above every due band (at most 7), a nearer due time never lowers the score, and every number is on the page for a person to check. Tests pin the table by example and by seeded property.
Where: `src/command_center/core/urgency.py`; contract in docs/contracts/core.md.
Revisit when: users ask to tune weights, estimated duration is allowed in (it is off by default), or the older 0-100 score is retired.
