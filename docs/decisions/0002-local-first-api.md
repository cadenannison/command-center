# 0002. Local-first backend, REST under /v1, phone over Tailscale

Status: accepted

Context: A separate mobile repo needs a stable contract and reach to the Mac without exposing it to the internet.
Decision: The backend runs on the Mac and binds 127.0.0.1. REST lives under `/v1`; `docs/generated/openapi.json` is the contract. The phone pairs by QR code and short-lived tokens, reaching the Mac through Tailscale Serve (never Funnel).
Consequences: The phone cannot reach a sleeping Mac; the app should say so rather than fail silently. /v1 paths are permanent (deprecate, never rename). Tokens expire quickly and are single-purpose.
