# 0015. Urgency is computed at read time; adapters leave it 0

Status: accepted

Context: An item's urgency depends on how far away its due date or start is, so it changes as the clock moves. `Event.urgency` is a stored field, and the sync runs on an interval (30 minutes by default).
Decision: Source adapters leave `Event.urgency` at 0. `AgendaService` (not built yet) scores each event when it reads, with `core.scoring.urgency(event, now)`, which ignores the stored value. Scores therefore follow the clock, not the time of the last sync.
Alternative: Score in the adapter (or in the store) when the item is fetched. The stored score would be correct only at sync time: an assignment due in 60 hours scores 70 at noon, but by the next afternoon it is due within 24 hours and should score 90, so it would stay wrong until the next sync, and indefinitely for a source that stopped syncing.
Reason: The score is a pure function of the event and `now`, so computing it where `now` is known is always correct and costs one cheap call per event. Passing `now` in keeps `core` deterministic (rule 1).
Where: `src/command_center/core/scoring.py`; rule 3 in `docs/contracts/adapters.md`; behaviour table in `docs/contracts/core.md`.
Revisit when: Ordering or filtering by urgency has to happen in the database (for example a paginated query that cannot score in Python), or scoring a window of events becomes measurably slow. Then store a derived score with an explicit refresh, in a new record.
