# 0211. The settings pages use the same loopback check as /pair and answer a phone 404

Status: accepted; completes 0106 for the web pages

Context: Decision 0106 keeps plain setting values (Canvas URL, Apple ID, weather coordinates) off a phone, but `GET /settings` and `GET /settings/{source}/status` prefill them and the route policy served those two GETs to a phone as reads, so a paired phone could open the page and read them.
Decision: Both routes carry the `require_loopback` dependency, the check `/pair` already had, now in `web/loopback.py` and shared: 404 "Not found" unless the Host is loopback and no proxy header is present. A tailnet Host, a loopback Host with a proxy header and an unclassified request all get it. Their rows in `tests/test_remote_policy.py` change from READ to HIDDEN, the same as `/pair`: the policy lets the request through and the page's own check answers. The PUT and DELETE routes stay DENIED by the policy.
Alternative: Strip the values for a phone but still serve the page (the shape of 0106's `/v1` fix); a second policy row type that refuses in the middleware.
Reason: The settings page is the Mac's own, with Connect forms and secrets handling; showing a phone a stripped copy has no use and a template that prefills is one edit from leaking. The 404 matches what the same phone gets for every other page that is not its own.
Where: `src/command_center/web/loopback.py`, `settings_routes.py`, `pair_routes.py` (now imports the shared check). Tests: `tests/test_web_settings_remote.py` (loopback 200, tailnet 404, proxy headers 404), `tests/test_remote_policy.py`.
Revisit when: A phone screen needs to show connection status (add a scoped read then, with its own decision).
