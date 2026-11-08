# Phone access (Tailscale Serve)

The phone talks to the same API as the web UI, through your tailnet. Nothing is exposed to the internet.

## Contract for the phone app
`docs/generated/openapi.json` (human copy: `api-reference.md`) is the contract. Pair with `POST /v1/pair`, keep the refresh token, call `POST /v1/pair/refresh` before the 15-minute access token ends, and send `Authorization: Bearer <access token>` on every other call. Behaviour and reasons: `docs/contracts/api.md`, decision 0057.

## What the phone can do
A paired phone is read-only, plus one write:
- **Allowed:** every GET (`/v1/events`, `/v1/agenda/...`, `/v1/attention`, `/v1/summary`, `/v1/settings` status, `/v1/devices`), `POST /v1/sync`, and the pairing calls themselves.
- **Refused with 403:** connecting or deleting a source (`PUT`/`DELETE /v1/settings/{source}`) and revoking a device (`DELETE /v1/devices/{id}`). Do those on the Mac. The web UI's own writes (the settings forms, making a pairing code) are not reachable from the phone either (404).
- Every write is JSON: send `Content-Type: application/json` on any body, or 415 (`/v1/pair` and `/v1/pair/refresh` answer a wrong declared type with 422). A write with no body (`POST /v1/sync`) needs no Content-Type. Do not send an `Origin` header (a native app does not): one that is not the server's own Host is refused with 403.
- Without a token the answer is 401 whatever the route.
A new write the phone needs is a change to `api/policy.py` and a decision record; it is not available by default (decision 0060).

## Set up (once)
1. Install Tailscale on the Mac and the phone and sign in to the same tailnet. Note the Mac's tailnet name, for example `my-mac.tail1234.ts.net`.
2. Tell the app that name, lowercase and without `https://` or a port: `CC_ALLOWED_HOSTS=my-mac.tail1234.ts.net` (comma separate more than one; the first is the one in the QR). Restart the server. An unlisted name is refused with 400.
3. Let Serve forward to the local server: `tailscale serve --bg 8765` (use your `CC_PORT`). **Serve only. Never run `tailscale funnel`**: Funnel puts the API on the public internet. Check with `tailscale serve status` that the entry is not marked as Funnel-enabled.
4. On the Mac open the menu-bar item, choose **Pair phone** (or visit `http://127.0.0.1:8765/pair`) and press **Show code**. Scan the QR in the phone app within 5 minutes. The code works once.
5. Paired phones are listed by `GET /v1/devices`; `DELETE /v1/devices/{id}` signs one out immediately.

## Limits and warnings
- The phone cannot reach a sleeping Mac. Keep the Mac awake (or accept that the app is offline while it sleeps). The menu-bar title reads "CC offline" when the server is down.
- Five wrong pairing attempts lock pairing for 60 seconds for everyone, because Serve makes every request look like it comes from 127.0.0.1.
- Losing a phone: revoke it from the web UI or the API. A reused refresh token revokes the device by itself.
- **Check once on a real tailnet:** the design assumes Serve forwards the request with the tailnet name in `Host` and adds forwarding headers. From the phone, `GET https://<name>/v1/settings` without a token must be 401 and `GET https://<name>/v1/health` must be 200. If the settings call answers 200 with no token, stop and open an issue: Serve is rewriting `Host`.

## Launch at login
The menu-bar item has **Launch at login**. It writes `~/Library/LaunchAgents/com.command-center.menubar.plist` (no secrets in it); it takes effect at your next login. Turn it off in the same menu.

The plist carries `CC_ALLOWED_HOSTS` and `CC_PORT` (neither is secret, and no other variable is ever written), copied from the environment of the app when you turn **Launch at login** on. So turn it on from an app started with the variables set. If you change either value, turn **Launch at login** off and on again to rewrite the plist (decision 0060). Without `CC_ALLOWED_HOSTS` the server that starts at login refuses the tailnet name.

## Other known limits
- A phone that loses the response to a refresh call must pair again: the server treats the retry as a stolen credential.
- A paired phone cannot change sources or revoke devices (see above). If you lose a phone, revoke it from the Mac.
- If the server crashes, the menu-bar title reads "CC offline" until you relaunch the app.
