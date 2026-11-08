# 0037. The summary route answers 404 while summaries are off; the response nests the summary

Status: accepted; the router is now mounted and the service built in app.py (0053)

Context: The card asks for `GET /v1/summary?date=` returning the summary plus `{provider, cached}`, a `router` that is not mounted, and no edits to `app.py`. Opt-in must hold by default (decision 0004).
Decision: `Container` gains `summary: SummaryService | None = None`. `None` means summaries are off: no provider was built and the route answers 404 `Summaries are off`. The composition root builds the service only when `Settings.summary_enabled` is true. The response is `{"summary": {headline, priorities, heads_up}, "provider": str, "cached": bool}`; `date` is required, as for the agenda routes. A provider failure is still 200 (`provider` `stored` or `template`). `SummaryService.for_day(day) -> str | None` is a plain-text view for the web page, which already reads `container.summary` through that method.
Alternative: (a) Flat body with `provider` and `cached` beside `headline`: harder to extend without clashing names. (b) 403/409 when off: the resource does not exist for this user, and 404 is what the agenda routes use for "no such thing". (c) A `SummaryService` that holds an `enabled` flag: a second place for the opt-in to be wrong; with no service there is no provider to call.
Reason: The default container cannot call a provider, which the default-disabled test checks directly. The new `Container` field has a default, so existing callers are unchanged. `/v1` paths are permanent, so the shape was chosen to grow by adding fields.
Not done (outside this card): mounting `api/summary_routes.router` in `api/factory.py` and building the service in `app.py`; until then `docs/generated/` does not list the route.
Where: `src/command_center/api/summary_routes.py`, `services/container.py`, `services/summary.py`; `docs/contracts/api.md`, `services.md`.
Revisit when: The router is mounted (rebuild `docs/generated/`; the mobile repo sees a new path), or per-request refresh is wanted.
