# 0046. A skipped Canvas course contributes no assignments, not no events

Status: accepted. Supersedes the "contributes no events" wording of 0041 (item 2 and the line "No access means no events"); the rest of 0041 stands.

Context: 0041 says a course whose assignments call returns 401 "contributes no events". The code does less: only that course's assignments are dropped. `fetch` still passes every active course, skipped or not, to the calendar query as `context_codes[]`, and the planner call is not per course, so a skipped course's planner items (discussions, quizzes, notes) and calendar events are still returned. Review of the 0041 change found the mismatch. The project manager decided to keep the code and correct the wording.
Decision:
1. A course whose assignments call returns 401 (on any page) contributes no assignments, including those of pages already read. Nothing else changes for it.
2. Its planner items and calendar events are still returned, because if Canvas returns them the user can see them. Returning them is accurate; hiding them would not be.
3. `SyncService.replace` therefore deletes the stored assignments of a skipped course in the window, and only those. Its stored planner items and calendar events are replaced by what Canvas returns, as for any other course.
4. 0041's other rules are unchanged: 401 on `/users/self`, the course list, planner and calendar calls is `AuthExpired`; each skip is logged at WARNING with the source, course id and error class only; 403 is throttling.
Alternative: exclude skipped course ids from the planner and calendar queries so that "no access" really means "no events" (matches the old wording, but hides items the user can see, and adds code to collect the ids and filter the planner items by course).
Reason: The code already behaves as in item 1, the user's real access decides what is shown, and the cheaper change is to correct the words.
Where: `src/command_center/adapters/canvas.py` (`_assignments`, `_calendar_events`); `docs/contracts/adapters.md` (rule 10 and the Canvas bullet). Tests: `tests/test_canvas_client.py`.
Revisit when: Canvas answers 401 to `calendar_events` when `context_codes[]` names a course the user cannot read. The whole sync then fails as `AuthExpired`, which is the case 0041 set out to prevent. Neither the Canvas docs nor 0041 confirm what Canvas does with such a code (it may silently drop it). If it happens, exclude the skipped course ids from the planner and calendar queries.
