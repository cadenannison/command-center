# 0039. Web UI: CSRF header, write-only forms, and the shapes it assumes of its neighbours

Status: accepted

Context: Task 2e builds the Jinja2 + HTMX pages. The card leaves several details open, and two neighbours (the weather adapter, the summary service) are built by other tasks.
Decisions:
1. CSRF: one random token per router (`secrets.token_urlsafe(32)`, constant-time compare). Every non-GET/HEAD/OPTIONS request needs it in the `X-CSRF-Token` header, else 403 before anything is read or parsed. Pages put it in `hx-headers` on `<body>`, so htmx adds it to every request. A form field or query parameter is not accepted. `create_router(container=None, *, csrf_token=None)`; `csrf_token` is there for tests.
2. Container lookup: `create_router()` without a container reads `request.app.state.container`, as the API does, because the production container is built at startup (decision 0021).
3. Forms are write-only: inputs are never prefilled, not even plain settings. A card shows "set" per field and, for secrets only, the last 4 (the service's `SecretStatus` already hides it under 8 characters). Only the fields the page defines for a source are read from a submission; other posted keys are ignored. Values are trimmed and capped at 8192 characters (the API's bound).
4. A blank field keeps the stored value because the service merges key by key. A fully blank submit on a source with nothing stored is refused without calling the service; on a configured source it is passed on as empty credentials, so Reconnect works and the adapter decides what empty means.
5. Double submit: besides `hx-sync="this:drop"` and a disabled button in the browser, the router refuses a second connect for a source whose connect is still in flight ("Already connecting"). The Connect button is also disabled while the source is `syncing`; the status poll re-enables it through an out-of-band swap when the sync ends.
6. Placement: an item sits on the local day of its `start`, else `due`. An item that began before the window shows on the window's first day, labelled "Ongoing". Weather items appear only in the Today weather strip.
7. Weather strip: shows each weather event's `title` and local time only. The weather adapter should put the human-readable forecast in `title`; `raw` is not read.
8. Summary: `container.summary` is optional. None means no block. The block shows `for_day(day)` text; a failure shows "Summary unavailable right now" and logs only the exception class.
9. Item links are rendered only when http(s); everything else is dropped (links come from outside).
10. CSS is inline and `<script>` points at `/static/vendor/htmx.min.js` only: no CDN, fonts or other requests. Responses are `Cache-Control: no-store`.
Alternative: CSRF token in a cookie or form field (a cookie adds state and the card says per-process); prefilling plain settings (contradicts "show only set").
Reason: Each keeps the secret surface at one place (the PUT body) and the router thin; the rest follow the card.
Where: `src/command_center/web/`; `tests/test_web_*.py`; `docs/contracts/web.md`.
Revisit when: Weather events get a defined shape; `connect` validates against stored values (see web contract, "Known gap"); a CSP is wanted once the vendored htmx file is known.
