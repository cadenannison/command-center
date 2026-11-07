# 0023. 422 responses do not echo the request input

Status: accepted

Context: FastAPI's default 422 body includes the submitted `input` for each failing field. For `PUT /v1/settings/{source}` that input is the credentials, so a malformed request would send the secret back in a response.
Decision: A `RequestValidationError` handler returns only `loc`, `msg` and `type` per issue, in FastAPI's `{"detail": [...]}` shape. The `ConnectRequest` model also hides `credentials` from its `repr`.
Alternative: Keep the default and rely on clients not to log it; validate the credential fields by hand.
Reason: "No response carries credentials" has to hold for error responses too, and the documented shape stays the same.
Where: `src/command_center/api/errors.py`, `src/command_center/api/settings.py`; `docs/contracts/api.md`.
Revisit when: A route takes a body that needs `input` in its errors for debugging; scope the handler to the settings routes then.
