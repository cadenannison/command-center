# 0377. The Week widget groups GET /v1/events by local day in pure helpers

Status: accepted

Context: The Week widget needs a per-day count and the next event. `GET /v1/agenda/week` is Monday-based and the spec says the week starts on the user's local first day; `GET /v1/events?from&to` takes any window.
Decision: Use `/v1/events` with the window [local first day midnight, +7 calendar days). The first day comes from `Intl.Locale` week info (Sunday, the design's convention, if unavailable). Days are built with calendar arithmetic, so DST days of 23 or 25 hours stay one day. A ranged event counts on every day it overlaps (an end exactly at midnight does not reach the next day); a point item on its day. Calendar events count when Calendar is a selected source; other open items count by due time when their source is selected; weather, done and timeless items never. Tiers: height 1 the strip only, height 2 adds the next event ("Now:" when under way), height 3 adds up to 3 items per day; source dots from width tier 2. Today is highlighted with a ring and `aria-current="date"`; each day's accessible name holds the date and count. The clock is always a parameter.
Alternative: `/v1/agenda/week` (rejected: Monday-based, server timezone). Filtering by kind on the server (no such parameter).
Reason: Local-day grouping on the client is the only way to honour the user's week start without an API change.
Consequences: Calendar feeds all show one Calendar dot (the API has no per-calendar field in the UI contract).
Where: `ui/src/features/dashboard/week-model.ts`, `week-widget.tsx`.
Revisit when: the API gains a week-start or a per-calendar field.
