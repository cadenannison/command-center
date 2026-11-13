# 0401. The undated cap counts only visible tasks, and writes read the ledger row after the lock

Status: accepted

Context: Review of card A1a found that dismissed undated tasks, which stay dismissed for good, used slots of the 200-item undated cap (0372) and could push open tasks out of `/v1/tasks` and `/v1/needs-me`; and that a ledger write read its row before taking the event-row lock, so on Postgres a write that waited decided on a stale row and could leave an item dismissed and snoozed, or done and dismissed.
Decision: `AgendaService` applies the dismissed and snoozed filter before the cap: it asks the store for the cap, counts what the filter hides, and asks again for that many more (at most four times, stopping when the store returns fewer rows than asked), then keeps the first 200 that show. Checked-off tasks still count against the cap as before (0372). `SqliteItemLedger` locks the event row first and then reads the ledger row with `populate_existing` in `dismiss`, `snooze`, `check_off`, `set_note` and `restore`; restore now takes the same lock before its empty-row cleanup.
Alternative: Add an `exclude` argument to `EventStore.undated_open` (rejected: a port change that every fake would need). Raise the cap (rejected: it only delays the problem). A row-level `SELECT ... FOR UPDATE` on the ledger row instead of reading fresh (rejected: the event-row lock already serialises writers to one item, and SQLite has neither).
Reason: The widening needs no port change and costs one extra query only when something is hidden. Reading after the lock is the smallest change that makes "the latest action wins" true under contention.
Consequences: A store with more than 200 undated tasks and many dismissed ones may run up to five queries. Two writers racing on one item are serialised by the event-row lock on Postgres and the write lock on SQLite; only a test with two real connections can show the Postgres wait.
Where: `services/agenda.py` (`_undated_visible`), `storage/sqlite_items.py` (`_known_row`, `_fresh_row`, `restore`, history). Tests: `tests/test_dismiss_snooze_followups.py`.
Revisit when: the undated cap changes, or the store can filter hidden items itself.
