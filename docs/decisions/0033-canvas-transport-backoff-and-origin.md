# 0033. Canvas transport: throttling, origin pinning and the second module

Status: accepted; partly superseded by 0041 (a 401 on one course's assignments skips that course instead of raising AuthExpired)

Context: The Canvas adapter sends a bearer token and follows `Link` URLs that Canvas supplies. The throttling doc says a throttled request gets "429 Forbidden (Rate Limit Exceeded)" and may carry `X-Rate-Limit-Remaining`; the task card also says 403. `SyncService` already retries a `TransientError` three times (1 s, 2 s, 4 s).
Decision:
1. 403 and 429 are both throttling. Each is retried up to 3 times after 2 s, 4 s, 8 s (a numeric `Retry-After` replaces the delay, capped at 30 s), then `TransientError`. Every retry is logged with its attempt, delay and reason code, never a URL or token.
2. `X-Rate-Limit-Remaining` below 50 on a successful response pauses 2 s before the next request. It never fails the fetch.
3. Every `Link` rel="next" URL must have the same scheme, host and port as the checked base URL; otherwise `FatalError` and nothing is sent, so the token cannot be sent elsewhere or over http. Redirects are not followed. A repeated next URL, or more than 200 pages of one list, is a `FatalError`.
4. 401 is `AuthExpired`, 5xx and network errors `TransientError`, any other non-2xx `FatalError`. A pydantic `ValidationError` becomes a `FatalError` whose text omits the input (decision 0023).
5. The transport is in `adapters/canvas_client.py`, the mapping in `adapters/canvas.py`, to stay under the 300-line aim. Neither imports a vendor SDK, only `httpx`.
Alternative: treat only 429 as throttling and a 403 as `FatalError` (matches the docs; a rate-limited 403 would then fail the sync at once, and the card says 403); read the 403 body for "Rate Limit" (the body text is not documented); fail on a low quota (a slow sync is better than none); follow `Link` URLs without a host check (what the docs imply; sends the token wherever the response points); one file.
Reason: The nested retry is bounded: at most 4 attempts of each request here, and `SyncService` repeats the whole fetch at most 4 times. A genuine 403 (forbidden) costs about 14 s of sleeping before `SyncService` reports "unreachable" instead of a precise error; that is the price of following the card.
Where: `src/command_center/adapters/canvas_client.py`; tests `tests/test_canvas_client.py`.
Revisit when: A Canvas 403 that is not throttling shows up in practice; then read the body or split the cases.
