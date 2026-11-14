# 0405. Request lines from the HTTP client libraries are not logged at INFO

Status: accepted

Context: httpx logs every request URL at INFO ("HTTP Request: GET <url>") and the root logger is INFO. An iCal feed URL is a secret (AGENTS.md rule 5), but only the geocode URL was filtered, so a feed URL could reach the log.
Decision: `configure_json_logging` sets the `httpx` and `httpcore` loggers to WARNING. Adapters log their own fixed-text events with a source id, never a URL. The existing geocode filter stays as a second line.
Alternative: a per-URL filter in each adapter (rejected: every new adapter or caller must remember it, and one miss leaks a secret; one level setting at the configuration point covers all callers).
Reason: the leak is in a library's log line, so the fix belongs where logging is configured, not at each call site.
Consequences: less debugging detail from the HTTP libraries by default; WARNING and above from them still reach the log. Anyone lowering these loggers must know request URLs are secrets (layer note in adapters/CLAUDE.md). No public interface changes.
Where: `adapters/json_log.py` (`configure_json_logging`), both composition roots already call it. Tests: `tests/test_httpx_log_quiet.py`.
Revisit when: a URL-redacting log filter exists that is applied to every handler, or the HTTP client library is replaced.
