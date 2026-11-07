# Contract: api

REST under `/v1`, bound to 127.0.0.1. `docs/generated/openapi.json` (and `api-reference.md`) hold every route, parameter and schema and are the machine contract for the separate mobile repo; this file holds behaviour and reasons only.

## Behaviour
- `create_app(container)` (`api/factory.py`) takes a `Container` or a factory called at startup (decision 0021). The production app is `command_center.app.create_app()`.
- Only the `Host` headers `localhost` and `127.0.0.1` (any port) are served; anything else is 400 (`TrustedHostMiddleware`). Reason: stops a web page on another origin from reaching the API through a rebinding hostname.
- Handlers parse, call one service method and return; logic lives in services.
- `GET /v1/health`: `{"status": "ok"}`. Liveness for the launcher and the phone.
- `GET /v1/events?from&to`: events overlapping `[from, to)`, scored now, ordered by time. Both bounds must carry a timezone; write `+` as `%2B` or use `Z`. `to` not after `from` is 422.
- `GET /v1/agenda/{day|week|month}?date=YYYY-MM-DD`: the day, Monday-based week or month containing `date`, in the configured timezone. `date` is required.
- `GET /v1/attention`: urgent items and owed or overdue email, most urgent first (see `services.md`).
- `GET /v1/settings`: per source, per key `{set, last4}`, plus the last sync state (`syncing | ok | reconnect | error`). Write-only: no value is ever returned.
- `PUT /v1/settings/{source}` with `{"credentials": {key: value}}`: validates and stores, then returns at once with `sync.status` `syncing`; the sync runs as a background task after the response and ends in `ok | reconnect | error`, visible in `GET /v1/settings` (decision 0025). A rejected credential is **200 with `ok: false`** and nothing stored (decision 0020); the one exception is a secret store failure part-way through the writes, which reports `ok: false` and leaves the keys written so far. Unknown source is 404.
- `DELETE /v1/settings/{source}`: removes every stored key and every stored event of the source (decision 0029), so its items leave the agenda. Unknown source is 404.
- `POST /v1/sync`: syncs every source and returns each `SyncState`; a failing source is a state, not an error.
- No response model has a field that can carry a credential. A 422 (`ValidationErrorBody`, declared on every route that takes parameters) lists `loc`, `msg` and `type` only and never echoes the submitted input (decision 0023). A secret store failure appears as the error state `secret store unavailable`, never a 500 with detail.
- Events carry `raw`, which adapters must fill with public item fields only.

## Not built yet
- Summary opt-in, pairing.
- Auth: pairing tokens are short-lived; the phone reaches the Mac over Tailscale Serve, never Funnel.
