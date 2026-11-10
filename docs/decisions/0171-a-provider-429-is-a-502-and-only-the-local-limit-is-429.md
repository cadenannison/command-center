# 0171. A provider's 429 is a 502; only the service's own limit is 429

Status: accepted. Corrects one sentence of 0169.

Context: Decision 0169 said chat answers 429 "for the limit or a provider 429". The code maps a provider's rate limit (`ChatRateLimited`) to `ChatUnavailableError("rate_limited")`, which the route answers as 502 with the redacted text `The chat provider rate limited: ...`; `docs/contracts/api.md` and `tests/test_chat_routes.py` say 502. The second review found the mismatch.
Decision: 429 with `Retry-After` is only the service's own limit (10 messages per 60 seconds), where we know the wait. A provider's 429 or 503 is 502 with `reason` `rate_limited` in the service and a fixed sentence in the body, because the provider's `Retry-After` is not read or passed on (it would be the provider's text) and the client cannot tell how long to wait.
Alternative: Pass a provider 429 through as 429 with no `Retry-After` (a client would retry blindly, and a 429 from us would mean two different things).
Reason: A 429 from this API always carries a real `Retry-After`, and a client that sees 502 knows the failure is upstream.
Where: `src/command_center/services/chat.py` (`_ask`), `api/chat_routes.py`; `tests/test_chat_routes.py`; `docs/contracts/api.md` (Chat).
Revisit when: A provider's wait time is parsed safely, so a provider 429 can carry a real `Retry-After`.
