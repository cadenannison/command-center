# 0006. Apple Calendar, Canvas, weather

Status: accepted

Decision:
- Apple Calendar: iCloud CalDAV with an app-specific password. EventKit may come later as an option.
- Canvas: personal access token over httpx REST, validated with `GET /api/v1/users/self`.
- Weather: Open-Meteo (no key).
Consequences: caldav is imported only in `adapters/caldav_apple.py`; Canvas and weather use httpx with explicit timeouts and respx-mocked tests. Tokens and app passwords live in the keychain (0007).
Sources (checked 2026-11-07): https://open-meteo.com/en/terms does not support "Open-Meteo (no key)": it never mentions an API key, so that claim is unsourced. The page does state the terms that apply to this use: the free API is for non-commercial use only, with limits of 10,000 calls per day, 5,000 per hour and 600 per minute, and you accept the CC-BY 4.0 licence.
