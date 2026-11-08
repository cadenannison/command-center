# 0040. The stored-summary fallback looks only at earlier days: `latest_before(day)`

Status: accepted. Supersedes the `SummaryStore.latest()` clause of 0034.

Context: 0034 added `latest()` on the claim that today's row is a cache hit, so the fallback "can only be an earlier day". A review showed that is wrong: a row for a later day can exist (the user, or the phone, asked for tomorrow's summary). `latest()` would then answer a failure for today with tomorrow's briefing, labelled `stored`.
Decision: `SummaryStore.latest(user_id)` becomes `latest_before(day, *, user_id)`: the summary of the greatest stored day strictly before `day`, else `None`. `SummaryService` passes the requested day. With nothing earlier it falls back to the template.
Alternative: (a) Keep `latest()` and filter in the service: the port returns one row, so the service would have to pull them all. (b) Drop the stored fallback and always use the template: loses a real briefing after a rate limit, which the card asks for.
Reason: The card's "last stored summary" means the most recent one that can stand in for this day; a later day cannot.
Where: `src/command_center/core/ports.py`, `storage/sqlite_summary.py`, `services/summary.py`, `tests/fakes.py`; `docs/contracts/core.md`, `storage.md`, `services.md`.
Revisit when: A fallback older than a few days should be refused (add an age limit), or summaries expire (0035).
