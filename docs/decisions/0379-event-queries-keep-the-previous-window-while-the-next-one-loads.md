# 0379. Event queries keep the previous window while the next one loads

Status: accepted

Context: The Events, Week and Weather widgets put the date window in the query key. At midnight the window moves, the key changes, and the widget would drop to its loading state.
Decision: `useEvents` passes `placeholderData: keepPreviousData`, so the last data stays on screen until the new window arrives. One `useNow` hook (`use-now.ts`, a minute tick) replaces the copies in the Week and Weather widgets and serves Events. Known edge, left as it is: if the fetch for the new window then fails, TanStack drops the placeholder, the query has no data, and the widget shows its error panel with Retry. It does not fall back to the old window's data.
Alternative: Holding the last good data in a ref and showing it as stale after a failed new-window fetch (more machinery; the project manager chose not to add it).
Reason: A successful midnight change is the usual case and now never flashes; a failed one is a real failure for the new day.
Consequences: During the placeholder moment the rows are the previous window's, for as long as the new request takes. Tested in `use-events-window.test.tsx`.
Where: `ui/src/features/dashboard/use-events.ts`, `use-now.ts`.
Revisit when: a failed midnight refresh is seen in use.
