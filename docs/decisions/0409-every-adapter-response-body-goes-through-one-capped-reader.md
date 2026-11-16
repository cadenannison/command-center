# 0409. Every adapter response body goes through one capped reader

Status: accepted

Context: Canvas and the forecast read whole bodies with no limit, and the feed reader appended a chunk before checking its cap, so each could be made to hold an arbitrary body in memory.
Decision: `http_cap.read_capped(response, limit)` is the one reader. It refuses a declared length over the limit before any read and checks `len(body) + len(chunk)` before extending, so the buffer never exceeds the limit and the network overshoot is at most one chunk. Caps: 5 MiB per feed (as before), 2 MiB per Canvas page, 1 MiB per forecast. Over the cap is `FatalError` with fixed text and no URL. `read_feed_capped` keeps its name and signature and calls `read_capped`. Canvas and the forecast stream (`client.stream`); Canvas rebuilds a plain response holding the capped decoded body so its callers are unchanged. Feed and Canvas requests send `Accept-Encoding: identity`; the forecast does not, because Open-Meteo's replies are small and the decoded count already stops a compressed reply at the cap.
Alternative: a per-adapter cap loop (rejected: the count and the order of check and extend drift between copies, which is the bug in the old feed reader).
Reason: one implementation means one place to get the arithmetic right.
Consequences: an unusually large but legitimate calendar or course page now fails loudly (`FatalError`) instead of slowly. Field and item-count caps are not covered. Constants: `MAX_FEED_BYTES`, `MAX_PAGE_BYTES`, `MAX_FORECAST_BYTES`.
Where: `adapters/http_cap.py`, `ical_feed.py`, `canvas_client.py`, `weather.py`. Tests: `tests/test_adapter_body_caps.py`.
Revisit when: a real course list or calendar hits a cap, or a new adapter reads a body.
