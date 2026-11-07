# Contract: adapters

Concrete integrations. Each implements a core port; each vendor SDK is imported in exactly one file.

## Rules for every source adapter
1. Implement `SourceAdapter` (`core/ports.py`): `name`, `async validate(creds)`, `async fetch(creds, window)`.
2. Raise `AuthExpired` (credentials rejected: the user reconnects), `TransientError` (timeout, rate limit, 5xx: retry later) or `FatalError` (malformed data, unsupported request: do not retry). Translate vendor errors into these; never let an `httpx` or SDK exception escape.
3. Leave `Event.urgency` at 0. `AgendaService` scores at read time from `core.scoring.urgency`; a stored score would go stale.
4. Use `httpx` with an explicit timeout on every call. Tests mock it with `respx` fixtures and use made-up credentials; no real credentials, accounts or network.
5. Every user-supplied URL (a Canvas base URL, a pasted iCal feed) goes through `core.urlcheck.require_https_public`, and its host through `await net_guard.ensure_public_host(host)`, before any request is sent. Both raise `ValueError`; map it to `FatalError`. `ensure_public_host` can also raise `TransientError` on a lookup timeout; let that propagate.
6. No credentials in logs, exception messages or `Event.raw`. `raw` holds the source's public item fields only, never tokens, auth headers or request URLs that embed a key.
7. Each vendor SDK is imported in exactly one file, the one named for it in the import-linter contracts in `pyproject.toml` (see `docs/MAP.md`). A source whose SDK has no named file needs a decision first; do not add one to `pyproject.toml` from an adapter task.
8. Adapters import `core` only: no services, storage, api or app. Composition roots build them.

## Behaviour (built)
- `keyring_store.KeyringSecretStore` implements `SecretStore` over the OS keychain (the only importer of `keyring`). It keeps one keychain entry per `(user_id, source)` under the service name `command-center`: a JSON object of key to value. `set` reads, updates one key and rewrites the entry under a process-wide lock, which `delete` also takes, so threads in one process cannot lose each other's updates; a second process is not covered. Decision: docs/decisions/0012 (supersedes the adapter clause of 0010). `status` derives from `core.schema.secret_status`, so `last4` is `None` below 8 characters. `delete` of a missing entry is a no-op. Values are never logged, returned by `status`, or put in an error message.
- `SecretStoreError` is raised when the keychain cannot be used: no backend (`NoKeyringError`: "No OS keyring backend is available"), another `KeyringError` (the message carries only the exception class name), or a stored entry that does not parse (corrupt; the entry is not echoed). None of these chain the underlying exception. A corrupt entry keeps raising from `get`, `status` and `set` until the source is deleted: `delete(source)` removes it without parsing it, after which the keys can be entered again.
- `net_guard.ensure_public_host(host, timeout=5.0)` resolves `host` with `getaddrinfo` in a worker thread, waiting at most `timeout` seconds (`asyncio.wait_for`; not a config field), and passes every address through `require_https_public` (IPv6 in brackets, so `https://[::1]/`). It raises `ValueError` if the host does not resolve, resolves to nothing, or any address is not public; messages never echo the host or addresses. If the lookup times out it raises `core.errors.TransientError("host lookup timed out")`, which adapters let propagate (a retry may succeed), unlike the `ValueError`, which they map to `FatalError`. A thread cannot be cancelled, so the lookup thread may outlive the timeout and finish in the background; its result is discarded. Limitation: this checks the answer at check time only. A hostile DNS server can answer differently when the HTTP client connects (DNS rebinding), so this narrows SSRF but does not close it; pinning the connection to the checked address is not done.
- `system_clock.SystemClock` implements `Clock`: `datetime.now(UTC)`.

## Not built yet (file names are already fixed by the import contracts)
- `canvas.py`: Canvas REST over httpx, personal access token, validated by `GET /api/v1/users/self`.
- `caldav_apple.py`: iCloud CalDAV with an app-specific password (only importer of `caldav`).
- `ical_feed.py`: pasted iCal feed URLs, e.g. LearningSuite per-course feeds; no scraping.
- `gmail.py`: `gmail.readonly`, bring-your-own OAuth client; surfaces token expiry as "needs reconnect".
- `weather.py`: Open-Meteo over httpx.
- `summary_gemini.py`, `summary_ollama.py`: summary providers; Ollama is the local option.
- `queue_redis.py` / in-process queue: queue implementations.
- `menubar_rumps.py`: macOS menu-bar (only importer of `rumps`).
