# 0006. Apple Calendar, Canvas, weather

Status: accepted

Decision:
- Apple Calendar: iCloud CalDAV with an app-specific password. EventKit may come later as an option.
- Canvas: personal access token over httpx REST, validated with `GET /api/v1/users/self`.
- Weather: Open-Meteo (no key).
Consequences: caldav is imported only in `adapters/caldav_apple.py`; Canvas and weather use httpx with explicit timeouts and respx-mocked tests. Tokens and app passwords live in the keychain (0007).
