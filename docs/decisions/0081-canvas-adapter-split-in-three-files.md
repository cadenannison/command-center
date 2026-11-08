# 0081. `adapters/canvas.py` is split into the adapter, models and reads, with no change in behaviour

Status: accepted

Context: Task 4a. `canvas.py` was 315 lines, over the 300-line aim of `.claude/rules/style.md`, and held four things: the response models, the adapter class, the four reads and the `Event` mapping helpers. Decision 0033 had already moved the transport to `canvas_client.py`.
Decision: along the seams the file already had, unchanged code moved to:
- `canvas_models.py` (63 lines): the pydantic response models (`Course`, `Assignment`, `CalendarEvent`, `PlannerItem`, ...) and `parse_rows` (the error text still drops the input, decision 0023). The leading underscore was dropped from the names because they are now imported across modules.
- `canvas_fetch.py` (207 lines): `SOURCE`, `CONTEXT_CODE_LIMIT`, `active_courses`, `assignments`, `planner_events`, `calendar_events`, `date_params` and the private mapping helpers (`_event`, `_in_window`, `_calendar_params`, `_iso`, `_absolute`). Each takes an open `CanvasClient`.
- `canvas.py` (72 lines): `CanvasAdapter` (`name`, `validate`, `fetch`) and `DEFAULT_LOOKBACK_DAYS`. `fetch` is the same sequence: courses, each course's assignments, planner items, then calendar events last.
The public import (`command_center.adapters.canvas.CanvasAdapter`) and the constructor are unchanged. No test was edited: `test_canvas_adapter.py` and `test_canvas_client.py` pass as they were (96 passed).
One thing is deliberately not "moved": the skipped-course warning is still emitted by the logger named `command_center.adapters.canvas`, set by name in `canvas_fetch.py`, because `test_a_skipped_course_is_logged_by_id_and_error_class_without_a_url_or_token` filters on that name and operators may too. With `getLogger(__name__)` it would have become `...canvas_fetch`, a visible change.
Alternative: (a) Leave `canvas.py` at 315 lines (the aim is not a rule, but the card asked for the split). (b) Put the mapping helpers in a fourth file: each of the three files is under 210 lines, a fourth would be under 60 and split the "read, then map" steps from each other. (c) Keep the logger name by importing `logger` from `canvas.py` into `canvas_fetch.py`: that would make `canvas_fetch` import `canvas`, which imports it back.
Reason: three files with one job each, a smaller diff to review per change, same behaviour.
Where: `src/command_center/adapters/canvas.py`, `canvas_models.py`, `canvas_fetch.py`; contract `docs/contracts/adapters.md`, `docs/MAP.md`.
Revisit when: another Canvas read is added (Out of v1: grades, announcements) and `canvas_fetch.py` nears 300 lines; then split reads from mapping.
