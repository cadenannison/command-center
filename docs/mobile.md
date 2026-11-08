# Phone access (Tailscale Serve)

The phone talks to the same API as the web UI, through your tailnet. Nothing is exposed to the internet.

## Contract for the phone app
`docs/generated/openapi.json` (human copy: `api-reference.md`) is the contract. Pair with `POST /v1/pair`, keep the refresh token, call `POST /v1/pair/refresh` before the 15-minute access token ends, and send `Authorization: Bearer <access token>` on every other call. Behaviour and reasons: `docs/contracts/api.md`, decision 0057.

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

**Known limit:** the plist carries no environment, so an app started at login does not see `CC_ALLOWED_HOSTS` or `CC_PORT`. The server it starts then refuses the tailnet name until a settings file exists (decision 0057, item 12). Until then, start the app from a shell that has the variables set if you want phone access.

## Other known limits
- A phone that loses the response to a refresh call must pair again: the server treats the retry as a stolen credential.
- A paired phone can do everything the web UI can, including changing sources and revoking other devices.
- If the server crashes, the menu-bar title reads "CC offline" until you relaunch the app.
