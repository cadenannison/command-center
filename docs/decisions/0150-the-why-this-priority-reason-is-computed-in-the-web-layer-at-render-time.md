# 0150. The "Why this priority" reason is computed in the web layer at render time

Status: accepted

Context: Task B2 asks each row to say why it has its priority. `explain(event, now)` already exists in `core/scoring.py` and returns the sentence ("Due in 10 hours, not done"); the lists show the number only.
Decision: `web/views.py` calls `explain` for every row it builds, with the agenda's own clock (`agenda.now()`), so the reason is always the one the badge's number was scored with. No field is added to `Event` or to any API schema; `openapi.json` is unchanged. The reason is shown as a tooltip on the badge and as "Why this priority:" in the row's details panel. A done item shows the core's own text for it.
Alternative: Store the reason on `Event` (or return it from `/v1/agenda`) so the phone gets it too; compute it in `services/agenda.py`.
Reason: The reason is derived from fields the row already has plus the clock, so storing it would add a second copy to keep in step with the score. An API field is a breaking-change decision for the mobile repo (AGENTS.md) and this task is web-only.
Where: `src/command_center/web/views.py` (`to_row`, `Row.reason`), `tests/test_web_items.py`, `tests/test_web_tasks.py`.
Revisit when: The mobile app wants to show the reason; add it to the API as a deliberate, additive change.
