# 0123. History is grouped by local day in the settings timezone and read over a from/to range

Status: accepted

Context: `GET /v1/history` has to say what was done on which day. The days must be the user's days, and on a day with 23 or 25 hours a fixed 24-hour step would put an item on the wrong day.
Decision: The route takes `from` and `to` (dates, inclusive, in the settings timezone) and returns one `HistoryDay` per day that has something, oldest first, each with `done_by_you`, `done_by_source` and `gone` lists. Entries carry item_id, title, source, kind, link, the time, `completed_by` (`user`, `source`, or null for a removal) and the note. The service turns the dates into a window with `day_window` (start of `from` to the end of `to`, both local midnights) and `group_history_range` assigns each instant to the local date it falls on, so the 25-hour day on 2026-11-01 and the 23-hour day on 2026-03-08 each hold their own entries and nothing leaks over midnight. `to` before `from`, or more than 366 days inclusive (`MAX_HISTORY_DAYS`), is a 422 that does not echo input. The history needs no item service to exist: without one the route is 404 `Items are not enabled`.
Alternative: A `days=N` count back from now (cannot ask for a past month, and a DST day has no clean meaning for "N days"); store the local date in the ledger row when the event happens (it would be wrong after the user changes their timezone setting).
Reason: A range over local dates is what a day, week or month page asks for, and computing the day at read time from UTC instants keeps one source of truth.
Where: `src/command_center/api/items.py`, `services/items.py` (`history`), `core/ledger.py` (`group_history_range`); tests in `tests/test_ledger_history.py` and `tests/test_core_ledger_range.py` (Denver, both DST changes).
Revisit when: A client needs paging or a count over a longer span than a year.
