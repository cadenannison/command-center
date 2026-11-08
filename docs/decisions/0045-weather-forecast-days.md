# 0045. Weather: one Event per forecast day, local midnight, 20-minute cache

Status: accepted

Context: Task 2c asks for one `weather` Event per day from Open-Meteo, with a 20-minute in-process cache through the injected `Clock`.
Decision:
- `start` is local midnight of the forecast day in the zone Open-Meteo reports (`timezone=auto`; the fixed `utc_offset_seconds` is the fallback if the zone name is unknown). `end`, `due` and `link` stay empty.
- A day whose maximum or minimum temperature is null (beyond the model's range) is skipped; a null rain probability drops only the ", N% rain" part. Temperatures round to whole degrees.
- The cache holds the parsed Events per `(latitude, longitude)` for 20 minutes of `Clock` time and is filled only by a successful fetch. A hit keeps the original `fetched_at`. The window filter runs on every call, after the cache. `validate` asks for one day, bypasses the cache and checks the coordinates first.
- 429 and 5xx are `TransientError`; any other non-200 and a malformed body are `FatalError`; a timeout or network error is `TransientError`. Messages never contain the coordinates. Redirects are not followed.
- The URL is fixed and public, so the user-URL guard of adapters rule 5 does not apply. `wind_speed_unit=mph` is sent as the card says, although no wind figure is read yet.
Alternative: Cache the raw JSON and rebuild Events each call; fail the whole fetch on a null day.
Reason: Caching Events keeps the cache hit free of parsing, and a null day is missing data, not a broken source.
Where: `src/command_center/adapters/weather.py`, `tests/test_weather_adapter.py`.
Revisit when: wind or "feels like" is shown, or the app serves more than one location (the cache is already keyed by location but unbounded).
Sources (checked 2026-11-07): https://open-meteo.com/en/docs gives the endpoint `https://api.open-meteo.com/v1/forecast`, `daily` variables `temperature_2m_max`, `temperature_2m_min`, `precipitation_probability_max`, and `temperature_unit=fahrenheit`, `wind_speed_unit=mph`, `timezone=auto`, `forecast_days` 0-16 (default 7); `timezone` is required when `daily` is requested. Gmail field names from the discovery document bundled in google-api-python-client 2.201.0 (`gmail.v1.json`): `Thread.snippet`, `Message.labelIds`/`snippet`/`internalDate` (int64 string, epoch ms), `ListThreadsResponse.threads`/`nextPageToken`, `threads.list` `maxResults` (max 500).
