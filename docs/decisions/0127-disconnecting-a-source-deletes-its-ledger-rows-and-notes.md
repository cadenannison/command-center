# 0127. Disconnecting a source deletes its ledger rows and notes

Status: accepted

Context: Disconnecting a source already deletes its events, sync state and stored data, and the user expects "disconnect" to mean the data is gone. Ledger rows hold titles and notes of that source's items.
Decision: Both purge paths, `SyncService.purge` (single process) and `QueuedSyncService.purge` plus the sink's `purge_stale` and the leftover purge inside `apply` (distributed), delete the source's ledger rows, notes included, through `ItemLedger.delete_source`. Local tasks (source `local`) and other sources are never touched. A sync whose fetch finishes after the disconnect leaves no rows. In distributed mode the sink's generation check makes it write nothing. In single-process mode there is no generation: the sync's write lands, then `SyncService` sees that the source was forgotten and deletes the events and ledger rows again (decision 0029); if that cleanup fails it is logged and the rows stay until the next disconnect. A note or check-off that races the disconnect is handled by decision 0128. `docs/contracts/api.md` and `docs/mobile-api-notes.md` say so, so a client does not assume history survives a disconnect.
Alternative: Keep notes and history after a disconnect (a reconnect gets them back, but the user who disconnects to remove their data finds it still there); delete only the notes.
Reason: Disconnect is the user's data-removal control, and leaving titles behind would defeat it.
Where: `src/command_center/services/sync.py`, `services/queued_sync.py`, `storage/sqlite_sink.py`, `storage/sqlite_ledger.py` (`delete_source_ledger`); tests in `tests/test_ledger_sync.py` and `tests/test_ledger_sink.py`.
Revisit when: A reconnect should restore history; the rows would then be archived instead of deleted, with their own retention rule.
