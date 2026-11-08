# Contract: web

Jinja2 + HTMX pages over the services. Imports services and core only. Decisions: 0008, 0038, 0039.

## Public API
- `command_center.web.create_router(container=None, *, csrf_token=None) -> APIRouter`. Mount it at `/`. It is hidden from OpenAPI. Without `container` it uses `request.app.state.container`.
- Mount it only on an app that has the API's `TrustedHostMiddleware` (`api.factory`): the CSRF token sits in the page, and the Host check is what stops a DNS-rebinding page from reading it. The router does not check the Host itself.
- The page expects `/static/vendor/htmx.min.js` to be served by whoever mounts it (not in this repo yet). Nothing else is loaded from outside.

## Routes
| Path | Method | What |
|---|---|---|
| `/?date=` | GET | Today: summary (if `container.summary`), agenda, weather strip, needs-attention |
| `/week?date=` | GET | Seven Monday-based columns; day load = sum of urgency |
| `/month?date=` | GET | Grid heat by load (0-4 against the busiest day) and top deadlines (8, open, most urgent first) |
| `/settings` | GET | A card per registered source |
| `/settings/{source}/status` | GET | Status fragment, polled every 2 s while `syncing`; also re-renders the Connect button |
| `/settings/{source}` | PUT | Connect (form fields); returns the card, with `syncing`; the sync runs as a background task |
| `/settings/{source}` | DELETE | Disconnect; returns the card |

`date` is optional (default: `AgendaService.today()`); a bad date is 422. Unknown source is 404.

## Behaviour
- Every non-GET needs header `X-CSRF-Token` equal to the process token, else 403 (checked first).
- Settings fields per source: canvas `base_url`, `token`*; apple_calendar `username`, `app_password`*; learningsuite `urls`*(textarea); gmail `client_json`*(textarea); weather `latitude`, `longitude`; gemini `api_key`*. (* secret: password input or masked textarea.) Gemini's card states the free-tier training caveat (decision 0004).
- No response contains a submitted value. Cards show `set` and, for secrets, the last 4.
- Gmail's Connect shows "Waiting for Google sign-in…" and allows a 15 minute request; others 2 minutes. The button reads "Reconnect" when the state is `reconnect`.
- The weather strip footer is "Weather data by Open-Meteo.com" linking to https://open-meteo.com/ (CC-BY 4.0).

## Known gap
`SettingsService.connect` validates only the submitted fields, never the stored ones, so changing one field of a multi-field source (or Reconnect with nothing typed) hands the adapter a partial credential set. Adapters must treat missing fields as "ask the user" or the service should merge stored values before `validate`.
