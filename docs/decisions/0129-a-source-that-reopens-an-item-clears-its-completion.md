# 0129. An item the source reports open again loses its source completion

Status: superseded by 0130

Context: The reviewer found that `record_sync` stamped `done_by = "source"` on the first sync that saw an item done and never cleared it, and `overlay_marks` shows any item with a `done_by` as done. Canvas maps `submitted`, `graded` and `pending_review` to done, and a reset submission or an iCal task going back to needs-action is reported open again. The agenda then showed the item done, scored 0, and out of the attention list with no way for the user to undo it, because `undo` only clears a user check-off.
Decision: On every sync, a stored row with `done_by = "source"` whose item comes back with a status other than `done` has `done_at` and `done_by` cleared, and the row is deleted if nothing else is left in it (`_clear_reopened`). A user check-off is never cleared by a sync. A note is kept. If the source reports it done again, it is stamped again with that sync's time (first sight after the reopen). An item that vanishes from the source keeps its completion, as in decision 0122: only an item the source actually returns as open is reopened. The earlier completion is not kept in history.
Alternative: Keep the completion and show it in history while the agenda shows the item open (`overlay_marks` would apply only user marks and trust the event's own status; the history would then list something done that the source says is not); keep a separate "was reopened" record (more states for a rare case).
Reason: The source is the authority on what it completed, and a wrong "done" that hides an open assignment is worse than a missing history line. This is a judgement call the card does not cover.
Where: `src/command_center/storage/sqlite_ledger.py` (`record_sync`, `_clear_reopened`); tests in `tests/test_ledger_sync.py` (three cases).
Revisit when: History needs to show completions the source later took back; then store them as their own entry instead of clearing.
