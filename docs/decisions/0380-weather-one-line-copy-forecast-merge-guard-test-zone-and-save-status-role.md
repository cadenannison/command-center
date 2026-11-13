# 0380. Weather one-line copy, the fetched_at merge guard, the test zone and the save-status role

Status: accepted

Context: Review of the Weather, Week and dashboard work left four small items.
Decision: (1) Weather W1 reads "High 58° · Low 39°" and W2 "High 58° · Low 39° · 20% rain" (rain only when the forecast has a chance); the big number is hidden from assistive tech because the line states the high, and "high today" no longer appears twice. (2) A forecast entry whose `fetched_at` cannot be parsed counts as the oldest possible, so it never replaces a good entry for the same day (before, the comparison with NaN was false and it did). (3) The test timezone, America/Denver, is set once in `ui/vitest.config.ts` before any worker starts; the module-scope `process.env["TZ"]` lines in `week-model.test.ts` and `weather-model.test.ts` are gone, and `test-zone.test.ts` proves the zone and its DST offsets. (4) The dashboard save status has `role="status"` (a polite live region, no visual change).
Alternative: Keeping the sr-only "high today" (duplicated wording). Setting TZ in `globalSetup` (a second file for one line).
Reason: One clear line per tier; a bad timestamp must not hide a good forecast; one place for the zone; the saved confirmation is announced.
Consequences: The two Weather assertions of the old copy were changed in `weather-widget.test.tsx` under a `tests: modify` allowance for exactly those lines.
Where: `weather-model.ts` (`summaryLine`, `forecastDays`), `weather-widget.tsx`, `ui/vitest.config.ts`, `dashboard-view.tsx`.
Revisit when: the Weather widget gains current conditions (0376).
