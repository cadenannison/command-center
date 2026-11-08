# 0041. A 401 on one course's assignments skips that course

Status: accepted; partly superseded by 0046 (a skipped course contributes no assignments, not no events). Supersedes the clause of 0033 (item 4) that makes every 401 an `AuthExpired`.

Context: Review of the Canvas adapter found that Canvas can answer 401 when the token is valid but the user may not read something, for example an unpublished or locked course. With "401 is `AuthExpired`" one such course failed every sync and told the user to reconnect a working token. The project manager decided the rule for this case (Task 2a follow-up).
Decision:
1. `GET /api/v1/users/self` (validate) and the course list: 401 is still `AuthExpired`. So are planner and calendar calls: they are not per-course, and a token that cannot read them is not usable.
2. A 401 on any call for one course's assignments, on any page, skips that course: it contributes no events, including those of pages already read. "No access means no events."
3. Each skip is logged at WARNING with the source, the course id and the error class (`AuthExpired`), never a URL, token or course name.
4. This is the one explicit exception to `adapters.md` rule 10 ("never returns a partial result"). `SyncService.replace` deletes the stored events of a skipped course, which matches the user's real access. A 403 is unchanged: throttling (0033).
Alternative: keep every 401 fatal (the card as first written: one unreadable course blocks all of Canvas, and "reconnect" cannot fix it); skip on 401 only when the body says "not authorized" (the body text is not documented); skip a course on any 4xx (hides real errors such as a 404 from a bad path).
Reason: A course the user cannot read has nothing to show; the rest of the data is still correct and complete for what the user can see.
Where: `src/command_center/adapters/canvas.py` (`_assignments`); tests `tests/test_canvas_client.py`; `docs/contracts/adapters.md` (rule 10 and the Canvas bullet).
Revisit when: A token that Canvas has really revoked mid-sync shows up as a run of skipped courses. The planner call that follows would then raise `AuthExpired`, so this is covered today; revisit if that call is ever made optional.
