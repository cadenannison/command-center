# 0035. One cached summary per day; a failed day falls back without being stored

Status: accepted

Context: A provider call costs quota and sends data off the machine (0004). The card says a cache hit returns without calling the provider, and a provider error or rate limit returns the last stored summary, else the template.
Decision: `SummaryService.get(day)` returns the stored row for `day` if there is one. Otherwise it gathers the day's events (plus the attention list when `day` is today), builds the prompt and calls the provider once. A success is stored. `SummaryProviderError` (including `SummaryRateLimited`) returns `latest()` with `provider="stored"`, else `template_summary` with `provider="template"`. Fallbacks are never stored, so the next request retries the provider. Any other exception propagates (it is a bug). When there are no events to describe, the provider is not called and the template is returned, unstored. Requests are serialised by one lock, so two simultaneous requests for a new day make one call. A cache hit reports the configured provider's name, because the store keeps only the `DailySummary`.
Alternative: (a) Store the fallback: a rate limit at 6am would pin the template all day. (b) Catch every exception from the provider: hides bugs. (c) Store the provider name with the row so a cache hit names its true author: needs a column beyond "one row per user and day" and a `put` signature the card did not ask for.
Reason: The cost-bearing path runs at most once per successful day, and a failure costs the user nothing but a plainer summary.
Known limits: A summary built before the day's first sync stays until tomorrow (no expiry). If the user switches provider mid-day, a cache hit still names the new provider. Neither was asked for; both are cheap to add later.
Where: `src/command_center/services/summary.py`, `src/command_center/storage/sqlite_summary.py`; `docs/contracts/services.md`, `storage.md`.
Revisit when: Stale summaries are noticed (add an expiry or a refresh), or when the row grows a provider column.
