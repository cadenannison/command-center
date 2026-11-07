# Contract: services

Application logic. Depends on core ports only; never an adapter, storage or framework.

## Behaviour
Nothing yet.

## Not built yet
- Aggregation per source and per window; source-health tracking (`ok`, `needs reconnect`, `unreachable`).
- Summary orchestration: runs redaction, then the chosen provider, only when the user has opted in.
- Settings service: write-only secrets, returns status (set + last4).
- Pairing: issues and checks short-lived tokens.
