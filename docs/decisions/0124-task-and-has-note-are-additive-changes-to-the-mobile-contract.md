# 0124. `task` as an event kind and `has_note` on events are additive changes for the mobile contract

Status: accepted

Context: `openapi.json` is the contract for a separate mobile repo, so any API change is a breaking-change decision (AGENTS.md). Local tasks need an `EventKind` of their own, and the agenda needs to say that an item has a note without carrying the note.
Decision: `EventKind` gains `task`, and `Event` gains `has_note: bool` (default false; the note text is never part of an event). Both are additive: an old client that reads an event with an unknown kind must ignore it (not crash), and one that does not know `has_note` ignores the field. The new routes are additions under `/v1`: `POST /v1/items`, `PATCH` and `DELETE /v1/items/{id}`, `POST`/`DELETE /v1/items/{id}/done`, `PUT`/`DELETE /v1/items/{id}/notes`, `GET /v1/history`. Nothing under `/v1` is renamed or removed. The project manager approved the `task` kind (Option 1). `tests/test_schema.py` changed for it, and only there: the unknown-kind example became `bogus`, and `task` joined the accepted kinds.
Alternative: Reuse `assignment` for local tasks (a client could not tell the user's own tasks from Canvas work, and the ledger could not tell which source rows a sync may prune); a separate `/v1/tasks` resource (a second shape for something that already is an agenda item).
Reason: One item shape for the agenda keeps the phone's list code simple; an unknown-kind rule is the standard way to grow a closed set without a version bump.
Where: `src/command_center/core/schema.py`, `docs/generated/openapi.json` (rebuilt with `mise run gen:build`), `docs/mobile-api-notes.md`.
Revisit when: A mobile client cannot ignore unknown kinds; then `task` has to be gated behind a client-declared capability.
