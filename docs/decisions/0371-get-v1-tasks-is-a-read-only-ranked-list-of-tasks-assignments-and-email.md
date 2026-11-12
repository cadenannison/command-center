# 0371. GET /v1/tasks is a read-only ranked list of tasks, assignments and email

Status: accepted

Context: The Tasks widget needs the ranked list and the reasons (0332, 0302: a widget needs a /v1 endpoint first).
Decision: `GET /v1/tasks` (router `api/tasks.py`, always mounted, no parameters) returns `[{id, title, source, due, link, done, priority, reasons}]` for kinds `task`, `assignment` and `email` inside the sync horizon, check-offs applied, sorted by priority descending, then `due` ascending with no due time last, then id. `link` is the item's own link or null. Done items stay, with `done` true and priority 1. Calendar events and weather are not tasks. It is a read, so a paired phone may call it (POLICY row READ); there are no write routes, and dismiss is a later card. The logic is `AgendaService.tasks()` over `core.urgency.task_items`; the route only calls it.
Alternative: Add `reasons` to `/v1/attention` or `/v1/events` (rejected: those return Event and filter differently). Hide done items (rejected: the card asks for the done state, and the UI can filter).
Reason: A new additive route changes nothing for the mobile repo; reading is already the default for a phone.
Where: `src/command_center/api/tasks.py`, `services/agenda.py`, `core/urgency.py`.
Revisit when: pagination or a status filter is needed, or items beyond the 14 days back to 60 days ahead horizon matter.
