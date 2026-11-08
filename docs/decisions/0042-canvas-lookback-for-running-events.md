# 0042. Canvas planner and calendar queries start `lookback_days` before the window

Status: accepted. Resolves gap (a) of 0032, which stays accepted.

Context: `SyncService.replace` deletes whatever `fetch` omits from the window, and `adapters.md` rule 10 says a span that began before `window.start` and still runs must be returned. The Canvas docs for `calendar_events` and `planner/items` do not say whether an item that started before `start_date` is returned. If Canvas matches on the start, a multi-day event would vanish from the store after its first day. The project manager chose the fix (Task 2a follow-up).
Decision:
1. `CanvasAdapter(clock, sleep, lookback_days=7)`. Planner and calendar requests send `start_date = window.start - lookback_days` (UTC instant); `end_date` is unchanged.
2. Everything returned is trimmed locally with the store's rule (spans by overlap, points by start in the half-open window), so an item that ended before the window is dropped.
3. A negative `lookback_days` is treated as 0.
4. Assignments are unaffected: they carry a due date, are read per course without a date filter, and are filtered locally.
Alternative: send `start_date = window.start` and rely on Canvas to return running events (undocumented; a wrong guess silently deletes events); `all_events=true` (returns every event, unbounded); a lookback computed from the longest stored event (needs store access, which an adapter does not have).
Reason: One extra week of items is cheap to fetch and trim; the lookback turns an undocumented behaviour into one the adapter does not depend on.
Limit: An event that began more than `lookback_days` before the window and is still running is missing if Canvas matches on start. Seven days covers a normal term event; raise the parameter at the composition root if longer events matter.
Where: `src/command_center/adapters/canvas.py` (`DEFAULT_LOOKBACK_DAYS`, `_date_params`); tests `tests/test_canvas_adapter.py` (the mock in `tests/canvas_support.py` returns only items starting on or after `start_date`, the strictest reading of the docs).
Revisit when: A live response shows Canvas returns running events for a plain `start_date`; the lookback could then go to 0.
