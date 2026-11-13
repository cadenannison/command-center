# 0386. GET /v1/needs-me is a read-only list; the 0-100 attention scorer stays until a card retires it

Status: accepted

Context: The Needs me widget needs a /v1 endpoint first (0302). The rule is 0385. `/v1/attention` and `core/scoring.urgency` (0-100) already exist and the Jinja UI uses them.
Decision: `GET /v1/needs-me` (router `api/needs_me.py`, always mounted, no parameters) returns `[{id, kind, title, source, at, link, priority, reasons[{code, points, text}]}]`. `at` is the due time, else the start time (the one time the row sorts by). `link` is the item's own link or null, as in `/v1/tasks` (0371). Read-only: a paired phone may call it (POLICY row READ), there are no write routes. `AgendaService.needs_me()` shares `_task_rows()` with `tasks()`: the horizon query, the open undated rows (cap 200, 0372) and the ledger marks, so no new store query exists and nothing runs differently on Postgres. `tasks()` behaves as before. Items the user checked off are `done` after the marks and are excluded; there is no dismiss yet, so dismissed items cannot be excluded until that card adds it. The old attention list, `/v1/attention` and the 0-100 scorer are unchanged and stay until the card that retires them.
Alternative: Add the list to `/v1/tasks` as a filter (rejected: it also returns events and a different row shape). Remove or rewire `attention()` now (rejected: the frozen Jinja UI reads it; retirement is its own card). A `due` and `start` pair on the row (rejected: one sort time is simpler for the widget).
Reason: Additive route, so the mobile repo's contract only grows; one shared row builder means Tasks and Needs me cannot disagree about check-offs.
Where: `src/command_center/api/needs_me.py`, `services/agenda.py`, `api/factory.py`, `tests/test_needs_me_api.py`, `tests/test_remote_policy.py`.
Revisit when: dismiss exists, the old attention scorer is retired, or more than 200 undated open items matter.
