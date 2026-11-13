# 0400. Hidden items leave every list, and History gains a dismissed bucket and an outcome field

Status: accepted

Context: The card says GET /v1/tasks, /v1/needs-me, the events routes and the summary input must exclude dismissed and currently snoozed items, and History must list dismissed items with a kind field. Those routes treat done differently (the events and tasks routes keep done items with `status` done).
Decision: The agenda service drops a dismissed or currently snoozed item from every view it builds: day, week, month, between (`/v1/events`, chat context), attention, tasks, needs-me and so the summary input. Done items keep their existing treatment. `ItemService.get` and the action replies are not filtered, so a client can show the state it just set. History: `HistoryDay` gains a `dismissed` list and `HistoryGroup` the value `dismissed`; `LedgerEntry` gains a computed `outcome` ("done", "dismissed", "gone"). The existing `kind` field is the item's kind (email, assignment) and is permanent, so the new field is named `outcome`, not `kind`. The frozen web History page ignores the new bucket.
Alternative: Filter in each route (rejected: the summary and chat would each need it). Reuse `kind` for the outcome (rejected: renaming a persisted identifier, 0302). Keep dismissed items in day views with a flag (rejected: the spec says they leave every widget).
Reason: One filter in the agenda service is the single place every read passes through.
Consequences: Dismissed items no longer reach the AI summary or chat, which also suits rule 6. The chat history context lists only the existing three buckets.
Where: `services/agenda.py`, `core/ledger.py`, `storage/sqlite_items.py`; `tests/test_dismiss_snooze.py`.
Revisit when: a screen needs to list snoozed items, or the web History page should show dismissals.
