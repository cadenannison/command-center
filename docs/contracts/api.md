# Contract: api

REST under `/v1`, bound to 127.0.0.1. `docs/generated/openapi.json` is the machine contract for the separate mobile repo; this file holds behaviour and reasons only.

## Behaviour
- `GET /v1/health` returns `{"status": "ok"}`. Reason: liveness for the launcher and the phone.

## Not built yet
- Day/week/month views, source status, settings (write-only secrets), summary opt-in, pairing.
- Auth: pairing tokens are short-lived; the phone reaches the Mac over Tailscale Serve, never Funnel.
