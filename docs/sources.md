# Sources

Connect each one in the app under **Settings**. Values you type are stored in the OS keychain and are
never shown again; the card only says what is set and the last 4 characters of a secret.
The adapter behaviour behind each is in [contracts/adapters.md](contracts/adapters.md).

| Source | Settings fields | Setup |
|---|---|---|
| Canvas | Canvas URL, Access token | [Canvas](#canvas) |
| Apple Calendar | Apple ID, App-specific password | [Apple Calendar](#apple-calendar) |
| LearningSuite | iCal feed URLs | [LearningSuite](#learningsuite) |
| Gmail | OAuth client JSON | [gmail-setup.md](gmail-setup.md) |
| Weather | Latitude, Longitude | [Weather](#weather) |
| Gemini (summaries) | API key | [Summaries](#summaries) |

## Canvas
1. In Canvas open Account > Settings > Approved Integrations > **New Access Token**.
2. Give it a purpose such as "Command Center" and copy the token (Canvas shows it once).
3. In Settings > Canvas enter your school's address, for example `https://school.instructure.com`, and the token.

Canvas must be reachable over HTTPS on a public address. Assignments, planner items and calendar
events are imported; grades and announcements are not.

## Apple Calendar
1. Sign in at https://account.apple.com, open Sign-In and Security > App-Specific Passwords and create one.
2. In Settings > Apple Calendar enter your Apple ID and that password, not your normal Apple password.

## LearningSuite
1. In LearningSuite, copy the iCal (calendar subscription) link of each course.
2. In Settings > LearningSuite paste them one per line. The links are treated as secrets.
3. If it connects but shows no items, run `uv run command-center diagnose learningsuite`; [first-run.md](first-run.md#5-learningsuite-connects-but-shows-0-items) explains each answer.

## Gmail
Gmail needs a Google OAuth client of your own, created once. Follow [gmail-setup.md](gmail-setup.md). While
the client is unverified, Google expires the sign-in every 7 days and the card shows **Reconnect**.

## Weather
Enter the latitude and longitude of the place you want a forecast for, for example `40.2338` and
`-111.6585`. Forecasts come from [Open-Meteo](https://open-meteo.com/) and need no account.

City search: `GET /v1/geocode?q=Provo` (from this Mac only) lists up to 5 matching places with their coordinates, and never picks one for you; you choose and enter that place's latitude and longitude. The city name you type is sent to Open-Meteo's geocoding service (`geocoding-api.open-meteo.com`, location data based on [GeoNames](https://www.geonames.org/)) and nowhere else. It is not logged here, and searches are limited to 10 a minute. The Weather form does not use it yet.

## Summaries
The AI summary is off by default and sends nothing anywhere until you turn it on. Only titles, due
dates and trimmed subjects are sent, never email bodies. It is built the first time you open a day
and then kept.

| Setting (environment) | Meaning |
|---|---|
| `CC_SUMMARY_ENABLED=true` | Turn summaries on |
| `CC_SUMMARY_PROVIDER` | `gemini` (default) or `ollama` (a local model at `http://localhost:11434`) |
| `CC_SUMMARY_MODEL` | Override the provider's default model |
| `CC_SUMMARY_INCLUDE_EMAIL=true` | Let trimmed email subjects into the summary |

### Gemini key
Create a key in [Google AI Studio](https://aistudio.google.com/apikey), then enter it in Settings > Gemini
summaries. It is checked with one small request to Gemini before it is stored in the keychain (source
`gemini`, key `api_key`), and works at once: no restart. Deleting it stops new Gemini summaries: a summary already made for a day is kept, a later day shows the
latest earlier summary, and with none stored the built-in fallback is used. The key alone does not turn summaries on, that is
`CC_SUMMARY_ENABLED=true`.

On Gemini's free tier Google may use what you send to improve its products, and human reviewers may read it.
Only titles, due dates and trimmed subjects are sent, with email addresses and numbers redacted first, never
email bodies.
