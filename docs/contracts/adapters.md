# Contract: adapters

Concrete integrations. Each implements a core port; each vendor SDK is imported in exactly one file.

## Behaviour
Nothing yet.

## Not built yet (file names are already fixed by the import contracts)
- `canvas.py`: Canvas REST over httpx, personal access token, validated by `GET /api/v1/users/self`.
- `caldav_apple.py`: iCloud CalDAV with an app-specific password (only importer of `caldav`).
- `ical_feed.py`: pasted iCal feed URLs, e.g. LearningSuite per-course feeds; no scraping.
- `gmail.py`: `gmail.readonly`, bring-your-own OAuth client; surfaces token expiry as "needs reconnect".
- `weather.py`: Open-Meteo over httpx.
- `summary_gemini.py`, `summary_ollama.py`: summary providers; Ollama is the local option.
- `keyring_store.py`: OS keychain secret store.
- `queue_redis.py` / in-process queue: queue implementations.
- `menubar_rumps.py`: macOS menu-bar (only importer of `rumps`).
