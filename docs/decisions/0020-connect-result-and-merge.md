# 0020. Connecting reports rejection in the result; credentials merge key by key

Status: accepted

Context: `PUT /v1/settings/{source}` validates credentials. They can be rejected (`ValidationResult.ok` false, or `AuthExpired`/`TransientError`/`FatalError` raised by `validate`). The card also says to store "each field" and merge `updated_creds` "key by key".
Decision: Rejection is not an HTTP error. If the secret store fails part-way through the writes, the keys already written stay stored and the result is `ok=false` (no per-key rollback: the port has no per-key delete and the store is already failing). The response is 200 with `ConnectResult(ok=false, message)` and nothing is stored or synced. An unknown source is 404; a malformed body is 422. Stored keys that the request does not mention are kept (the request is merged into what is stored); `DELETE` removes everything. `validate` receives exactly the submitted credentials, not the merged set.
Alternative: 4xx for a rejected credential, which the mobile client could not tell apart from a bad request; replace the whole secret on every PUT, which loses keys that cannot be re-entered; validate the merged set, which lets a stale key change the outcome.
Reason: One body shape to read, no half-states, and `SecretStore` is already per key (0010).
Where: `src/command_center/services/settings.py`; `src/command_center/api/settings.py`; `docs/contracts/api.md`.
Revisit when: A client needs the status code, or a source needs partial updates validated against stored keys.
