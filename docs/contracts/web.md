# Contract: web

Jinja2 + HTMX pages over the services. Imports services, core and `pairing` (the QR only). Decisions: 0008, 0038, 0039, 0054, 0058.

## Public API
- `command_center.web.create_router(container=None, *, csrf_token=None) -> APIRouter`. Mount it at `/`. It is hidden from OpenAPI. Without `container` it uses `request.app.state.container`.
- Mount it only on an app that has the API's `TrustedHostMiddleware` (`api.factory`): the CSRF token sits in the page, and the Host check is what stops a DNS-rebinding page from reading it. The router does not check the Host itself.
- The page expects `/static/vendor/htmx.min.js`. The file is vendored at `web/static/vendor/htmx.min.js` (htmx 2.0.11, decision 0054) and `api.create_app` serves `web/static` at `/static`. Nothing else is loaded from outside.

## Routes
| Path | Method | What |
|---|---|---|
| `/?date=` | GET | Today: summary (if `container.summary`), agenda, weather strip, needs-attention |
| `/week?date=` | GET | Seven Monday-based columns; day load = sum of urgency |
| `/month?date=` | GET | Grid heat by load (0-4 against the busiest day) and top deadlines (8, open, most urgent first) |
| `/settings` | GET | A card per registered source and integration |
| `/settings/{source}/status` | GET | Status fragment, polled every 2 s while `syncing`; also re-renders the Connect button |
| `/settings/{source}` | PUT | Connect (form fields); returns the card, with `syncing`; the sync runs as a background task |
| `/settings/{source}` | DELETE | Disconnect; returns the card |
| `/pair` | GET | The pairing page (loopback Host only, else 404) |
| `/pair/code` | POST | Mints a one-time token and returns the QR (SVG) and the token; CSRF-protected, loopback only; says how to set `CC_ALLOWED_HOSTS` when no tailnet host is configured |

`date` is optional (default: `AgendaService.today()`); a bad date is 422. Unknown source is 404.

## Behaviour
- Every non-GET needs header `X-CSRF-Token` equal to the process token, else 403 (checked first).
- Settings fields per source: canvas `base_url`, `token`*; apple_calendar `username`, `app_password`*; learningsuite `urls`*(textarea); gmail `client_json`*(textarea); weather `latitude`, `longitude`; gemini `api_key`*. (* secret: password input or masked textarea.) Gemini is credential-only (`SourceForm.credential_only`): its card shows "Connected" once the key is set (never "syncing", never polled), asks "Delete the stored key…" and PUT does not queue a sync. Its card states the free-tier caveat, that email addresses and numbers are redacted before sending, and that saving a key does not turn summaries on (decisions 0004, 0058).
- `/pair` and `/pair/code` are for the local browser only: a remote Host (or a loopback Host with a proxy header) gets 401 from the auth middleware without a token and 404 from the route with one (decision 0057). The QR holds `{"v":1,"url":"https://<tailnet host>","token":...}`; the token is never in a URL. These responses are the only ones that carry a secret, and only the one-time token.
- No response contains a submitted value. Cards show `set` and, for secrets, the last 4.
- Gmail's Connect shows "Waiting for Google sign-in…" and allows a 15 minute request; others 2 minutes. The button reads "Reconnect" when the state is `reconnect`.
- The weather strip footer is "Weather data by Open-Meteo.com" linking to https://open-meteo.com/ (CC-BY 4.0).

## Known gap
`SettingsService.connect` validates only the submitted fields, never the stored ones, so changing one field of a multi-field source (or Reconnect with nothing typed) hands the adapter a partial credential set. Adapters must treat missing fields as "ask the user" or the service should merge stored values before `validate`.
