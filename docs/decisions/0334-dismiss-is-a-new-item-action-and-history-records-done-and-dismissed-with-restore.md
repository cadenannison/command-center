# 0334. Dismiss is a new item action, and History records Done and Dismissed with Restore

Status: accepted

Context: Today an item can be checked off or snoozed. Some items are noise (an email that needs no reply) and should leave the list without counting as done work. The spec adds a History screen.
Decision: Dismiss is a new item action beside Snooze in an expanded item. A dismissed item leaves every widget. History is a ledger of Done and Dismissed items grouped by day, newest first, with counts and total estimated time per day, search and All / Done / Dismissed filters. Today's items can be restored (Restore returns the item to its lists). Dismiss and Restore are /v1 endpoints (additive, 0302) and a service rule, not UI state.
Alternative: Treat dismiss as a check-off (rejected: it inflates "Done today" and the time totals). Delete the item (rejected: not recoverable and the next sync would bring it back). Restore for any day (rejected for version 1: the spec limits it to today).
Reason: Done and Dismissed mean different things to the person; keeping both in one ledger makes mistakes recoverable. A sync must not resurrect a dismissed item, so the state belongs in storage.
Consequences: A new item state with a storage change (additive column or table), an openapi.json change reviewed as additive, and sync logic that keeps the dismissed state. The ledger already records check-offs; this extends it.
Where: not built yet; `core` (state), `services`, `storage`, `api`, then `ui/`.
Revisit when: restore should reach older days, or dismissals should expire.
