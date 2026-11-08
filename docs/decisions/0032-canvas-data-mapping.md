# 0032. Canvas data mapping: planner dates, de-duplication, windowing and status

Status: accepted; gap (a) is resolved by 0042 (lookback before the window)

Context: Task 2a maps Canvas assignments, planner items and calendar events to `Event`. The Canvas docs (read 2026-11-07) leave four things open: the planner list has no documented top-level date field, `plannable` is documented only for `planner_note`, the assignments list has no date filter, and `calendar_events` returns the personal calendar unless `context_codes[]` is given (ten at most).
Decision:
1. A planner item's time is the first of `plannable.start_at`, `plannable.todo_date`, `plannable.due_at`. `plannable_date` is not used: the raw planner page does not mention it. An item with none of them is left out (`adapters.md` rule 9).
2. Planner items of type `assignment` are skipped: the per-course fetch returns them with their submission state. Calendar events seen by both the planner and `calendar_events` share one id (`calendar_event:<id>`); the calendar copy wins because it has an end.
3. `calendar_events` is called once without `context_codes[]` (personal calendar) and once per ten `course_<id>` codes, with `excludes[]=description`. Date bounds are sent as UTC instants; Canvas bounds are inclusive and the window is half-open, so the adapter re-applies the store's rule (spans by overlap, points by start in `[start, end)`) to everything it keeps.
4. Assignments have no date filter, so every assignment of every active course is read and kept only if `due_at` is in the window. Courses with `access_restricted_by_date` are skipped.
5. Assignment status is "done" for submission state `submitted`, `graded` or `pending_review` (the card says submitted or graded; the docs list `pending_review` as a submitted state awaiting grading), else "open". A missing or `unsubmitted` submission is "open".
6. Missing `base_url` or `token` in `fetch` raises `AuthExpired` (the user must reconnect); `validate` returns `ok=False` with a message instead.
7. Course ids and assignment ids are parsed as ints before they reach a URL path.
Alternative: use `plannable_date` (real responses carry it, but the docs do not, and the card says not to code from memory); keep planner assignments too (shows every assignment twice, once without status); fetch `type=assignment` calendar events instead of per-course assignments (no submission state without a second call); treat `pending_review` as open (a submitted quiz would stay on the to-do list).
Reason: Only documented fields can be trusted to survive a Canvas release; the store deletes whatever `fetch` omits, so the filter has to match the store exactly.
Where: `src/command_center/adapters/canvas.py`; tests `tests/test_canvas_adapter.py`.
Known gaps (open, not decided): (a) whether `calendar_events` returns an event that began before `start_date` and is still running is not documented; if it does not, a long event is missing for the days after it began. (b) A quiz or graded discussion appears as an assignment and, through the planner, again as an event, because `plannable` carries no documented link back to its assignment. (c) A discussion topic's due date is not in a documented `plannable` field, so such a topic is left out.
Revisit when: A live Canvas response shows `plannable_date` or the missing fields; then supersede this record.
