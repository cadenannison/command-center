# 0095. Planner items carry their course, and the assignment match uses it

Status: accepted; supersedes 0094

Context: 0094 dropped a planner item that had an assignment's title and due instant. Two different items in different courses with the same title and due instant would be merged. A check of the stored Canvas events (2026-11-09) showed every planner `quiz` item (59) and `wiki_page` item (34) has `/courses/<id>/` in its link, and assignments already carry `course_id` in `raw`.
Decision: `planner_events` reads the course id from the first `/courses/<id>` in the item's link, stores it as `raw["course_id"]` on the event, and drops the item only when its course, title and start equal an assignment's `course_id`, title and `due`. A planner item whose link has no course falls back to the 0094 match (title and instant only).
Alternative: Read a top-level `course_id` or `context_code` on the planner item (not read today, and the pinned docs for the planner list are not confirmed to define them), or add a first-class `course` field to `Event` (a persisted schema change for one adapter's need).
Reason: The link is a field the adapter already reads, so the match needs no new response field; it removes the cross-course merge. The fallback keeps a quiz with no link from showing twice; there the 0094 risk remains.
Where: `planner_events` and `_course_id` in `src/command_center/adapters/canvas_fetch.py`; tests `test_a_planner_quiz_sharing_an_assignments_title_and_due_in_another_course_is_kept`, `test_a_planner_quiz_without_a_link_still_matches_by_title_and_due`, `test_a_planner_event_is_tagged_with_the_course_in_its_link` in `tests/test_canvas_adapter.py`; `docs/contracts/adapters.md` (Canvas entry).
Revisit when: The UI shows the course on every item (then promote `course_id` to a field of `Event`, in its own record), or Canvas changes the link shape.
