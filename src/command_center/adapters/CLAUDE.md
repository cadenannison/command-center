# adapters

Contract: `docs/contracts/adapters.md` (large: read `## Rules for every source adapter`, then only the
section for the adapter you edit). Rules that load here: `.claude/rules/style.md`, `tests.md`.

- Imports `core` only, and never `storage`. Implements a Protocol from `core/ports.py`.
- Each vendor SDK is imported in exactly one file (`docs/MAP.md`, "Vendor SDK, one adapter file each";
  enforced by import-linter). Do not import `caldav`, `googleapiclient`, `google`, `keyring`, `redis` or
  `rumps` anywhere else.
- Outbound HTTP has no single guard; check what the path you touch already uses.
  - `net_guard.py` (SSRF check at DNS time): `ical_feed.py`, `chat_http.py`, `canvas_client.py`.
  - `http_cap.py` (1 MiB reply cap, read as a stream): `chat_http.py` (both the OpenAI-compatible and the
    Ollama chat providers), `weather_geocode.py` and `summary_ollama.py` (decisions 0222, 0246, 0288).
    Nothing else: `ical_feed.py` has its own 5 MB cap (`read_feed_capped`); the forecast, Canvas, Gmail,
    CalDAV and the Gemini SDK clients have none.
  - `trust_env=False` (no proxy from the environment): `chat_http.post_json`, `summary_ollama.py`,
    `weather_geocode.py` (its own client) and the Gemini SDK clients (decisions 0225, 0246).
- Nothing secret is logged or put in a URL (AGENTS.md rule 5). Test credentials start with `fake-`.
  Request URLs can be secrets (iCal feeds): `configure_json_logging` holds `httpx` and `httpcore` at
  WARNING; never lower these loggers (decision 0405).
- Tests mock HTTP with respx at the httpx boundary. Never hit a real service.
- A new adapter file needs a line in `docs/MAP.md` and the contract.
