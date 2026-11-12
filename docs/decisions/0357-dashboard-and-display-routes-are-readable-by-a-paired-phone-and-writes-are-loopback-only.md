# 0357. Dashboard and display routes: reads for a paired phone, writes loopback-only

Status: accepted

Context: Task R2 adds routes under /v1 (decision 0302). The phone policy is default deny for writes (0060, 0126).
Decision: `GET /v1/dashboards`, `GET /v1/dashboards/{id}` and `GET /v1/display-settings` are open to a paired phone. `POST /v1/dashboards`, `PUT /v1/dashboards/order`, `PUT` and `DELETE /v1/dashboards/{id}` and `PUT /v1/display-settings` are not in `REMOTE_WRITES`, so a phone gets 403 and nothing runs. Writes keep the JSON-only and cross-site rules for every caller. A write names the revision in `If-Match` (`"3"` or `3`): missing is 428, malformed is 400, a stale one is 409 `The revision is out of date; reload and try again`. Reads and writes answer `Cache-Control: no-store` and an `ETag` of the revision. Nothing in these bodies is a secret, so no response is redacted.
Alternative: Let a phone change its own display settings (rejected: the card says every write is loopback; the phone UI can come with its own decision). A `412` for a stale revision (rejected: the card says 409).
Reason: Layouts and display choices are not secret, but a phone should not rewrite the Mac's dashboards.
Consequences: The id routes take the path parameter `dashboard_id` (`tests/route_support.py` SAMPLE knows it since task R2b). Task R2 first shipped it as `item_id` because that helper could not be edited; it was renamed before any commit, so the typed client never had the old name.
Where: `src/command_center/api/dashboards.py`; `tests/test_remote_policy.py`, `tests/test_dashboards_remote.py`, `tests/test_dashboards_api.py`.
Revisit when: the phone app edits layouts or display settings.
