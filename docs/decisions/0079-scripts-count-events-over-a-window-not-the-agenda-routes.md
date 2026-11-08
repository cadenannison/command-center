# 0079. The scripts count events with `GET /v1/events` over a window, not with `/v1/agenda/{period}`

Status: accepted

Context: Task 4b asks both scripts for the event count "from the agenda". `GET /v1/agenda/{day|week|month}?date=` returns the events of one calendar period. A weather forecast covers 7 days from today, so it can cross a week or a month boundary and no single agenda call would count it all; two or three calls would have to be merged and de-duplicated.
Decision: both scripts call `GET /v1/events?from&to` (the same events the agenda is built from, `docs/contracts/api.md`) with an explicit window and count by `source`. Smoke uses two days back to 30 days ahead, so the weather forecast fits and other sources' items do not matter (it counts `weather` only). report-state uses `CC_REPORT_PAST_DAYS` (default 30) back to `CC_REPORT_FUTURE_DAYS` (default 60) ahead and says the window in its output. The bounds are UTC with a `Z`, as the contract asks. Only counts are read; no title is printed.
Alternative: `/v1/agenda/month` for this and the next month (two calls, merged by event id): closer to "the agenda" in name but more code in shell for the same set of events.
Reason: one call, one window, the same count before and after in the smoke test; a count over a stated window is also what the project manager can compare between runs.
Where: `scripts/smoke-distributed.sh` (`count_weather`), `scripts/report-state.sh`.
Revisit when: the agenda gains a range form, or the events route changes (that is an API decision, `openapi.json`).
