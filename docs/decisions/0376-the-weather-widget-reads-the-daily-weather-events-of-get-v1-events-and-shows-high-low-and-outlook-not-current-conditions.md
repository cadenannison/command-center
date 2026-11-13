# 0376. The Weather widget reads the daily weather events of GET /v1/events and shows high, low and outlook, not current conditions

Status: accepted

Context: The card asked for current temperature, condition text and the next hours. No /v1 route returns those. The only weather data is `WeatherAdapter` (`adapters/weather.py`, decision 0045): one `weather` Event per local day, `raw = {high_f, low_f, rain_percent}`, Fahrenheit, 7 days, stored like any event and returned by `GET /v1/events` (kind `weather`). Location is not in the response, and `GET /v1/settings` shows coordinates to loopback only.
Decision: Build what the data supports, with no backend change. Width tier 1 shows today's high (large) and low. Tier 2 adds the rain chance and tomorrow (from height tier 2). Tier 3 adds the multi-day outlook: 2, 4 or all later days at height tier 1, 2, 3. "Current temperature" is replaced by today's high, "next hours" by tomorrow; there is no condition text. Units are Fahrenheit as sent. States: no weather events means not connected (it cannot be told apart from a first sync that has not run); a failed refresh keeps the data as stale; a forecast whose newest `fetched_at` is over 6 hours old is also stale. The window is the start of yesterday to eight local days ahead; days are local dates of `start`.
Alternative: Stop the deliverable (rejected: the daily data is real and useful). Invent a current temperature from the high (rejected: false). Add a route (out of scope).
Reason: Honest, shippable subset; the gap is named so a backend card can close it.
Consequences: A follow-up backend card is needed for current conditions, hourly data and the location name (the adapter requests only `daily`). A location in a time zone far from the browser may label today's forecast as tomorrow's; not handled. Shared pieces: `use-events.ts`, `widget-state.ts`.
Where: `ui/src/features/dashboard/weather-model.ts`, `weather-widget.tsx`, `use-events.ts`, `widget-state.ts`.
Revisit when: the API returns current conditions, hours or a place name.
