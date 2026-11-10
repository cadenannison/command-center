# 0126. The item write routes are loopback-only; history is readable by a phone

Status: accepted

Context: A paired phone may today read everything and `POST /v1/sync` and nothing else (decision 0057, 0060). The new routes check off, annotate and create items, and the Mac's web UI is their only client in this task.
Decision: Nothing is added to `REMOTE_WRITES`, so `POST /v1/items`, `PATCH`/`DELETE /v1/items/{id}`, `POST`/`DELETE .../done` and `PUT`/`DELETE .../notes` are default-denied for a phone (403 `A paired phone may not do this`, before the handler). `GET /v1/history` is a safe method and stays open to a paired phone, notes included. The project manager approved adding the rows to `POLICY` in `tests/test_remote_policy.py` (Option 1) and nothing else in existing tests beyond `tests/test_schema.py`. `tests/test_items_remote_policy.py` proves the refusal and the read with concrete ids and checks that nothing changed.
Alternative: Let a phone check items off now (it needs a conflict rule between the two devices that this task does not have); loop the check into the handlers (a second place deciding who is remote).
Reason: Default-deny means a new route is safe until someone decides otherwise, and the policy table fails the build until each one is classified.
Where: `src/command_center/api/policy.py` (docstring), `tests/test_remote_policy.py` (rows), `tests/test_items_remote_policy.py`.
Revisit when: The mobile app needs to check items off; the routes move into `REMOTE_WRITES` and the rows become `SYNC`-like writes with their own rule.
