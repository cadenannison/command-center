# 0410. Which Canvas 403 is a throttle, and CalDAV permanent errors

Status: accepted

Context: every Canvas 403 was retried three times as rate limiting, and CalDAV not-found and forbidden answers fell into a transient catch-all, so a permission problem showed as "unreachable".
Decision: a Canvas 403 is a throttle only when its body contains "Rate Limit Exceeded" (case-insensitive); 429 stays a throttle; any other 403 is `FatalError("Canvas refused this request")`, not retried; 401 stays `AuthExpired`. In CalDAV, `AuthorizationError` stays `AuthExpired`; `NotFoundError` and a `DAVError` with status 403 or 404 are `FatalError` with fixed text; network errors and the catch-all stay `TransientError`, and the catch-all logs only the exception class (source and class, never exception text, a URL or a credential; decision 0405). No new failure class.
Alternative: treat every 403 as fatal (rejected: Canvas throttles with a 403, so a real throttle would stop retrying); inspect the `X-Rate-Limit-Remaining` header instead (rejected: it is sent on ordinary replies too, so it does not tell a throttle apart).
Reason: a retry cannot fix a permission or a missing calendar, and the retry delay hides the real cause from the user.
Consequences: if Canvas changes its marker text, throttles show as "Canvas refused this request", which is visible and safe. Canvas's marker is from the public API documentation as I know it; it was not checked over the network. A CalDAV forbidden that the library raises as `AuthorizationError` (it covers 401 and 403) still reads as "sign in again". Three existing Canvas test inputs gained the marker body (tests: modify, assertions unchanged).
Where: `adapters/canvas_client.py` (`_is_throttle`, `_raise_for_status`), `adapters/caldav_apple.py` (`_translate`). Tests: `tests/test_adapter_failure_classes.py`.
Revisit when: Canvas changes its throttle reply, or the caldav library separates forbidden from authorisation errors.
