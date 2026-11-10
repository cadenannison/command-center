# 0165. Chat routes are loopback only for paired phones, through the route policy

Status: accepted

Context: `GET /v1/chat/context-preview` returns the user's agenda text; `POST /v1/chat` spends the user's provider quota and sends that text out. A paired phone may read and sync but should not do either. The card says loopback only and extend `api/policy.py`.
Decision: `POST /v1/chat` and `DELETE /v1/chat/{id}` are writes, which a phone is already refused. `/v1/chat/context-preview` is added to `REMOTE_DENIED_READS` next to the city search (decision 0182). A phone with a valid token gets 403 and the service is not reached; a tailnet caller with no token is 401. Chat answers 404 on every chat route while chat is off, except the preview (decision 0169). `tests/test_remote_policy.py` needs three rows (`POST /v1/chat`, `GET /v1/chat/context-preview`, `DELETE /v1/chat/{conversation_id}`, all DENIED). That file blocks edits, so this task did not add them; they are listed in the report and `tests/test_chat_remote_policy.py` proves the behaviour meanwhile. The same applies to `route_support.SAMPLE` (no `conversation_id`) and the known-route list in `test_json_only_writes.py`.
Alternative: A check in each handler on the Host header (a second place that decides who is remote); a new route prefix outside `/v1` (the card names `/v1/chat`).
Reason: The policy file is where "what a phone may do" lives.
Where: `src/command_center/api/policy.py`, `api/chat_routes.py`; `tests/test_chat_remote_policy.py`.
Revisit when: The phone app gets its own chat; the openapi.json notes in `docs/mobile-api-notes.md` say these routes answer 403 today.
