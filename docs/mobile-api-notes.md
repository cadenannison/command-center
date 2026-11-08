# Notes for the mobile repo

Written for whoever builds the phone app in the separate mobile repo. Setup on the Mac (Tailscale,
pairing) is in [mobile.md](mobile.md); this file is what the app has to do and expect.

## The contract
[`generated/openapi.json`](generated/openapi.json) is the contract: every route, parameter and schema, and
the `DeviceToken` bearer scheme. Generate your client from it and re-generate when it changes.
[`generated/api-reference.md`](generated/api-reference.md) is a readable summary of the same file. If this
file and `openapi.json` disagree, `openapi.json` is right. An API change is a breaking-change decision in
this repo (`AGENTS.md`), so a diff of `openapi.json` between two commits is your change log.

Behaviour that is not in the schema (middleware refusals, scopes, reasons) is in
[contracts/api.md](contracts/api.md) and decisions
[0057](decisions/0057-phone-pairing-device-auth-and-menu-bar.md) and
[0060](decisions/0060-scoped-device-tokens-json-only-writes-and-plist-environment.md). [Decision index](generated/decision-index.md).

## Auth flow
1. The user shows a pairing QR on the Mac (menu bar "Pair phone", or `/pair` on the Mac). The code is
   single use and lives 5 minutes. The app reads it and calls `POST /v1/pair`
   `{"pairing_token": "...", "device_name": "..."}` (`device_name` is optional).
2. The 200 body is `{device_id, token_type: "bearer", access_token, access_expires_at, refresh_token}`.
   The access token lasts 15 minutes. Keep the refresh token in the phone's secure storage.
3. Send `Authorization: Bearer <access_token>` on every call except `GET /v1/health`, `POST /v1/pair`
   and `POST /v1/pair/refresh`. Send exactly one `Authorization` header.
4. Before the access token expires, call `POST /v1/pair/refresh` `{"refresh_token": "..."}`. The 200 body
   has the same shape as pairing. **The refresh token is single use: store the new one.** Presenting an old
   one again is treated as theft and revokes the device. A phone that loses the response to a refresh
   call cannot recover and must pair again.
5. Five failures in a row on `/v1/pair`, or five in a row on `/v1/pair/refresh`, lock that route for
   60 seconds for every caller (429 with a `Retry-After` header in seconds), because every request reaches
   the server from 127.0.0.1. A success resets the count.
6. Token responses carry `Cache-Control: no-store`. Never log or put a token in a URL.

The API is reached through the Mac's tailnet name over HTTPS (Tailscale Serve). A name that is not in the
Mac's `CC_ALLOWED_HOSTS` is refused before anything else. A sleeping Mac is unreachable.

## What a paired phone may do (decision 0060)
Scoped by default deny on the method:
- **Allowed:** every GET (`/v1/events`, `/v1/agenda/{period}`, `/v1/attention`, `/v1/summary`,
  `/v1/settings`, `/v1/devices`), `POST /v1/sync`, and the pairing calls.
- **Refused, 403:** `PUT /v1/settings/{source}` and `DELETE /v1/settings/{source}` (connecting or
  disconnecting a source) and `DELETE /v1/devices/{id}` (revoking a device). The user does those on the Mac.
- A request with no valid token is 401 whatever the route (except the three open routes above), so the
  app cannot probe for routes.
- A new write for the phone needs a change in this repo (`api/policy.py`) and a decision record. Do not
  assume one exists because `openapi.json` lists the route: the schema lists the route, the policy decides
  whether a phone may call it.

Writes under `/v1` are JSON only: any body needs `Content-Type: application/json` or the answer is 415
(on `/v1/pair` and `/v1/pair/refresh` a declared form or `text/plain` type is 422 instead).
A write with no body (`POST /v1/sync`) sends no Content-Type. Do not send an `Origin` header (a native
app does not by default): one that is not the server's own Host is refused with 403.

## `DELETE /v1/settings/{source}` also deletes the source's events
Disconnecting a source removes its stored credentials, **its stored events** and its sync state, so its
items leave `/v1/events`, `/v1/agenda/...` and `/v1/attention` at once (decisions 0029, 0074). The phone
cannot call it today (see above), but if it ever can, or if the app mirrors the agenda locally, drop
that source's cached events when its settings entry loses its keys. A later `PUT` brings the data back
with the next sync, not instantly: `PUT` returns `sync.status` `syncing` and the result shows in
`GET /v1/settings`.

## Error shapes
| Status | Body | When |
|---|---|---|
| 400 | plain text `Invalid host header` (not JSON) | the Host is neither loopback nor in `CC_ALLOWED_HOSTS` |
| 401 | `{"detail": "A valid device token is required"}` plus `WWW-Authenticate: Bearer` | missing, malformed, expired or revoked access token; same body for every cause. On `/v1/pair*` the `detail` is the refusal reason, still a 401 |
| 403 | `{"detail": "A paired phone may not do this"}` | a write outside the phone's scope |
| 403 | `{"detail": "Cross-site requests are not allowed"}` | a write with a foreign `Origin` or `Sec-Fetch-Site: cross-site` |
| 404 | `{"detail": "..."}` (`ErrorBody`) | unknown source, unknown device, `Summaries are off`, `Pairing is not available` |
| 415 | `{"detail": "Content-Type must be application/json"}` | a write with another or a missing Content-Type (a declared wrong type on `/v1/pair*` is 422) |
| 422 | `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` (`ValidationErrorBody`) | a bad parameter or body; the submitted value is never echoed |
| 429 | `ErrorBody` plus `Retry-After` (seconds) | pairing locked |

Not errors: a rejected credential on `PUT /v1/settings/{source}` is **200 with `ok: false`** and a short
message, and a source that fails to sync is a `SyncState` with status `error` or `reconnect`, never an
HTTP error. Treat 401 on an authenticated call as "refresh once, then pair again". Messages that come from
a source are redacted (addresses and long digit runs removed) and at most 200 characters.

Responses never contain a stored credential: `GET /v1/settings` returns `{set, last4}` per key.
