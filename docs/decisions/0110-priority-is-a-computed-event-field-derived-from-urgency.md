# 0110. Priority is a computed Event field derived from urgency

Status: accepted

Context: Users and the mobile app want a simple 1-10 priority beside the internal 0-100 urgency score. Items that are over (ended events, done assignments, weather) should show no priority.
Decision: `core/priority.py` holds `priority(urgency, *, done=False) -> int | None` = `ceil(urgency / 10)` clamped to 1..10 (integer arithmetic), `None` when `done` or urgency is 0, plus `MAX_PRIORITY = 10`. `Event` gets a pydantic `computed_field` `priority` that calls it with `self.urgency` and `done=self.status == "done"`. It is serialised (null when `None`) and appears in the OpenAPI response schema, but is not stored and does not affect equality; validating a dump that contains it still works because extra keys are ignored. `scoring.py` and the 0-100 scores are unchanged.
Alternative: (a) A stored `Event` field set by `AgendaService`: a second source of truth that can drift from urgency, needs a storage column and a migration. (b) A `priority(event, now)` function that rescored: duplicates scoring and can disagree with the stored urgency the rest of the app shows.
Reason: One derivation in core, pure, with no schema migration. Because it is computed from `urgency`, it cannot disagree with it. For the mobile repo, the `openapi.json` change is additive (a new nullable `priority` property on event responses), so it is not a breaking change.
Where: `src/command_center/core/priority.py`, `src/command_center/core/schema.py`; `tests/test_priority.py`; `docs/contracts/core.md`; `docs/generated/openapi.json` (regenerated).
Revisit when: Priority needs per-user tuning or non-linear buckets (then scoring tunables as data, see core.md Planned), or when the stored urgency can be stale enough that clients need a fresh rescore.
