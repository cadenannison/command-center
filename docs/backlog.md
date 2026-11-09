# Backlog

Features and changes we want, collected while testing. An item here is an idea, not a commitment: nothing
in this file changes the code or a contract. When an item is built, remove it from here and record the
choice in [decisions/](decisions/) as AGENTS.md requires.

Add an item as you find it: a title, why it matters, what it would take, and its status.
Status is one of `proposed` (written down, not yet decided), `accepted` (we will build it) or `blocked`.

## Weather: set the location by city name
- Status: accepted (future)
- Why: Settings > Weather asks for latitude and longitude. Open-Meteo's forecast API only takes
  coordinates, so today you have to look them up yourself (decision 0006, adapter in
  `adapters/weather.py`).
- Idea: take a city name, resolve it once with Open-Meteo's free geocoding API
  (`geocoding-api.open-meteo.com/v1/search`) during `validate`, and store the resolved `latitude` and
  `longitude`. Those keys are persisted, so they stay as they are (AGENTS.md: never rename).
- Open questions: show the matched place ("Provo, Utah, US") on the card so a wrong match is visible; the
  rule for an ambiguous name (take the first match and label it, or ask for "City, State").
- Touches: the weather adapter, the weather settings form (`web/sources.py`),
  `docs/contracts/adapters.md`, `docs/contracts/web.md`, `gen:build`. No new dependency (httpx is in use).
  It adds one outbound call to a fixed public URL, so it needs a new decision record.
- Interim: copy coordinates from Google Maps (right-click a place). Two decimals is plenty.

## Gmail connect: say what is happening while it waits
- Status: proposed (not decided)
- Why: after Google shows an error page (for example `access_denied` for a missing test user), the app never
  hears about it and keeps waiting up to 180 s for the sign-in. Pressing Connect again answers "Already
  connecting; wait for it to finish." with no hint why or for how long (decision 0039 item 5,
  `web/settings_routes.py`).
- Idea: reword the message to say it is waiting for the browser sign-in for up to 3 minutes, and that
  after a Google error you wait it out or restart the app.
- Alternative not chosen yet: let a new Connect replace the pending one. The sign-in thread cannot be
  cancelled, so a stale token could be stored when the old one finishes.
- Touches: the message in `web/settings_routes.py`, and `tests/test_web_csrf.py` (the task card must say
  `tests: modify`).
