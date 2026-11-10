# 0231. Changing a local task is an UPDATE that never inserts

Status: accepted. Adds `ItemLedger.update_local` to the port.

Context: `ItemService.update_task` read the task with `find` and then wrote the changed event with `save_local`, which is a merge (an upsert) in a second transaction. A delete that committed between the two removed the task, its note and its check-off, and the merge then inserted the event again without them: a resurrected task with no note and no check-off.
Decision: `ItemLedger.update_local(event) -> bool` runs one `UPDATE events SET ... WHERE user_id, id, source` (every column but the key and the source) and returns whether a row matched. The service raises `ItemNotFoundError` on False. `update_local` raises `ValueError` for an event that is not a local task, like `save_local`. `save_local` stays for `create_task`, which really does insert.
Alternative: Lock the row for the read and the write in one transaction (needs `find` and the write in one store call, and SQLite has no row lock); compare `fetched_at` and retry (a lost update would still need a rule for who wins); a new `Event` version column (a schema change for one race).
Reason: An UPDATE cannot insert, so a delete that wins the race stays won, on both databases, with no new column or lock. A concurrent update of the same task is last-writer-wins, as before.
Where: `src/command_center/core/ports.py` (`ItemLedger.update_local`), `src/command_center/storage/sqlite.py` (`update_local_event`), `src/command_center/storage/sqlite_items.py` (`update_local`), `src/command_center/services/items.py` (`update_task`); `tests/test_items_update_race.py` (SQLite).
Revisit when: Two tabs editing one task need conflict detection rather than last-writer-wins.
