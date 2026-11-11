# 0321. Today reads the day agenda for the browser's local date, and stale means old or a failed refresh

Status: accepted

Context: P1b needs one read-only /v1 endpoint that returns today's items. `GET /v1/agenda/day?date=YYYY-MM-DD` returns the events of the day containing `date` in the user's configured timezone, with no token on loopback. No endpoint returns "today" without a date, and no /v1 field exposes the configured timezone.
Decision:
- `/today` calls `GET /v1/agenda/day` with the browser's local calendar date (`localDateString`). No backend change. The date can differ from the server's "today" when the browser and the configured timezone differ; the contract owner may add a `today` shortcut later (additive, 0302).
- Four states from one pure function, `deriveTodayState`: loading (no data, no error), error (no data, an error: alert with a retry button), empty (an empty list), ready (rows). Rows are plain `<ul>` text; no visual design.
- Stale: data is on screen and either the last refetch failed, or it is older than 5 minutes (`STALE_AFTER_MS`). The page then shows a status line ("Could not refresh. Showing data from <time>.") and a Refresh button, and keeps the rows. The query refetches every 60 seconds.
- Retry policy is on the app's QueryClient (`createAppQueryClient`): network and server errors twice, nothing else (a 403 or 422 will not change by asking again).
Alternative: A new `GET /v1/today` (rejected: the card forbids a backend endpoint here). Send the server's date (not possible: the timezone is not in /v1). Treat only a failed refetch as stale (rejected: a tab left open for an hour would look current). A retry policy inside each hook (rejected: it overrides the test client and hides the policy).
Reason: The existing endpoint is enough for the plumbing slice; the stale rule matches what a person would call "this might be out of date".
Consequences: The time zone mismatch above. The 60 s poll and 5 min limit are placeholders for the design pass.
Where: `ui/src/features/today/`, `ui/src/api/query-client.ts`.
Revisit when: A date-less today endpoint or a timezone field is added, or the design pass sets freshness rules.
