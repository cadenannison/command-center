# Contract: web

Jinja2 + HTMX pages over the services. Imports services, core and `pairing` (the QR only). Decisions: 0008, 0038, 0039, 0054, 0058, 0100-0105.

## Public API
- `command_center.web.create_router(container=None, *, csrf_token=None) -> APIRouter`. Mount it at `/`. It is hidden from OpenAPI. Without `container` it uses `request.app.state.container`.
- Mount it only on an app that has the API's `TrustedHostMiddleware` (`api.factory`): the CSRF token sits in the page, and the Host check is what stops a DNS-rebinding page from reading it. The router does not check the Host itself.
- The page expects `/static/vendor/htmx.min.js`. The file is vendored at `web/static/vendor/htmx.min.js` (htmx 2.0.11, decision 0054) and `api.create_app` serves `web/static` at `/static`. Nothing else is loaded from outside.

## Routes
| Path | Method | What |
|---|---|---|
| `/?date=` | GET | Today: the summary card (always present, five states), agenda, weather strip, needs-attention |
| `/summary/settings?date=` | POST | Form `enabled` (`on` or `off`) and `provider`; stores them through `SummaryControl`; returns the card (`generating` when ready to generate). A different provider drops today's stored summary (decision 0115). 400 for an unknown provider or an `enabled` other than `on`/`off` (nothing is stored), 404 without a control |
| `/summary/generate?date=&refresh=` | POST | Generates (or, with `refresh=true`, regenerates) the day's summary; returns the card |
| `/week?date=` | GET | Seven Monday-based columns; day load = sum of urgency |
| `/month?date=` | GET | Grid heat by load (0-4 against the busiest day) and top deadlines (8, open, most urgent first) |
| `/settings` | GET | The setup checklist, then a card per registered source and integration |
| `/settings/{source}/status` | GET | Status fragment, polled every 2 s while `syncing`; also re-renders the Connect button |
| `/settings/{source}` | PUT | Form fields plus an optional `action` (decision 0102): `connect` (default) validates, stores and returns the card, with `syncing`, the sync running as a background task; `unverified` stores without validating; `test` validates the stored credentials and returns only the result line; `sync` starts a sync and returns the result line plus the status. Another `action` is 422 |
| `/settings/{source}` | DELETE | Disconnect; returns the card |
| `/pair` | GET | The pairing page (loopback Host only, else 404) |
| `/pair/code` | POST | Mints a one-time token and returns the QR (SVG) and the token; CSRF-protected, loopback only; says how to set `CC_ALLOWED_HOSTS` when no tailnet host is configured |

`date` is optional (default: `AgendaService.today()`); a bad date is 422. Unknown source is 404.

## Behaviour
- The Today summary card (`_summary.html`, section `#summary-card`, decision 0113) has states `off` (explains the opt-in and what is sent, Enable button when there is a control), `no_key` (Gemini chosen and the Gemini card has no key; links to `/settings#source-gemini`), `generating`, `ready` (text and a Regenerate button) and `error` (a fixed message by reason; provider text never shown). A page load never calls the provider (decision 0116): a summary already stored for the day is `ready` at once, otherwise the card is `generating` and its `hx-trigger="load"` posts `/summary/generate`, so the text arrives after the page. Generation happens once per day on first need; Regenerate is explicit. Disabled means no provider is called.
- Every row on Today, Week and Month prints a priority badge (`Row.priority`, decision 0114): the number always, colour from a CSS hue (green 1 to red 10) in light and dark; `–` when the item has no priority. The week column load and month heat still use urgency sums.
- Every non-GET needs header `X-CSRF-Token` equal to the process token, else 403 (checked first).
- Settings fields per source: canvas `base_url`, `token`*; apple_calendar `username`, `app_password`*; learningsuite `urls`*(textarea); gmail `client_json`*(textarea); weather `latitude`, `longitude`; gemini `api_key`*. (* secret: password input or masked textarea.) Gemini is credential-only (`SourceForm.credential_only`): its card shows "Connected" once the key is set (never "syncing", never polled), asks "Delete the stored key…" and PUT does not queue a sync. Its card states the free-tier caveat, that email addresses and numbers are redacted before sending, and that saving a key does not turn summaries on (decisions 0004, 0058).
- `/pair` and `/pair/code` are for the local browser only: a remote Host (or a loopback Host with a proxy header) gets 401 from the auth middleware without a token and 404 from the route with one (decision 0057). The QR holds `{"v":1,"url":"https://<tailnet host>","token":...}`; the token is never in a URL. These responses are the only ones that carry a secret, and only the one-time token.
- Which fields are secret is decided once, in `services.credential_fields` (decision 0100); `web/sources.py` derives `Field.secret` from it. Non-secret fields (canvas `base_url`, apple_calendar `username`, weather `latitude`/`longitude`) are prefilled with the stored value (`SourceSettings.values`), and after a failed submit with what was typed. A secret input is never prefilled, and a blank secret keeps the stored one. No response contains a secret value: cards show `set` and, for secrets, the last 4.
- A failed Connect changes nothing that is stored (the service writes only after `validate` passes). After a failure the secret inputs carry `hx-preserve`, so the browser keeps what was typed without the server sending it back (decision 0104; not exercised in a real browser).
- "Save anyway (unverified)" is shown only when `ConnectResult.can_save_unverified` is true, which is only after a `TransientError` (network), never after a rejected credential. It stores the typed values and records an `error` state starting "Saved unverified:", shown as "Needs attention" (decision 0101).
- Each card with something stored has "Test connection" (`action=test`) and, for a source that syncs, "Sync now" (`action=sync`); the result is a redacted line under the buttons (`#result-<source>`). Both are refused with a short message while another action on the source runs, and "Test connection" says to connect first when nothing is stored.
- Each card has a collapsible how-to (`<details class="howto">`, no JavaScript) from `web/howto.py`: Canvas base URL and token, Apple app-specific password, LearningSuite link, Gmail OAuth client, weather coordinates, Gemini key. Menu paths vendors change say "may differ" (decision 0103).
- The top of `/settings` is a checklist (`web/checklist.py`, `services.setup_checklist`): per source `Not connected`, `Connected` or `Needs attention` and the age of the last sync ("3 min ago"; "last attempt" when it did not end ok). The age uses the clock given to `SettingsService` (decision 0105).
- Gmail's Connect shows "Waiting for Google sign-in…" and allows a 15 minute request; others 2 minutes. The button reads "Reconnect" when the state is `reconnect`.
- The weather strip footer is "Weather data by Open-Meteo.com" linking to https://open-meteo.com/ (CC-BY 4.0).

## Past gap, fixed
Changing one field of a multi-field source (or Reconnect with nothing typed) used to hand the adapter a partial credential set. `SettingsService.connect` now merges the stored values under the submitted ones before `validate` (decision 0052; `docs/contracts/services.md`).
