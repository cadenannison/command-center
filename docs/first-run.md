# First run

Start Command Center on your own machine, connect your sources in the browser, and check that the first sync looks right. Setup for each source is in [sources.md](sources.md); this page is the order to do it in and what to expect.

## 1. Start it
```sh
mise install && mise run setup   # once after cloning
uv run command-center            # serves http://127.0.0.1:8765
```
Open http://localhost:8765 and go to **Settings**. The app only answers on your own machine, and it syncs when it starts and then every 30 minutes (`CC_SYNC_INTERVAL_MINUTES`).

## 2. Connect your sources: in the web page only
Type every secret into the Settings page in your browser and nowhere else. Not in the terminal (shell history and process lists keep what you type there), not in a `curl` command, not in an environment variable, not in a chat with a person or an assistant, not in an issue or a commit. The page stores each value only on this computer (in the OS keychain, or in a protected file when running under Docker) and shows only "set" and the last 4 characters afterwards.

| Source | What you enter in Settings | Where it comes from |
|---|---|---|
| Canvas | Your school's address and an access token | Canvas > Account > Settings > Approved Integrations > New Access Token ([sources.md](sources.md#canvas)) |
| Apple Calendar (iCloud) | Apple ID and an **app-specific password** | account.apple.com > Sign-In and Security > App-Specific Passwords; never your normal Apple password ([sources.md](sources.md#apple-calendar)) |
| LearningSuite | The iCal feed link of each course, one per line | LearningSuite course calendar subscription links; the links are secrets ([sources.md](sources.md#learningsuite)) |
| Gmail | The Google credentials file you download, then a browser sign-in | [gmail-setup.md](gmail-setup.md); read-only, and it needs a one-time Google Cloud project |
| Weather (optional) | Latitude and longitude | Any map; no account ([sources.md](sources.md#weather)) |

Connect one source at a time and let it settle before the next. Each card's button checks what you typed against the real service first: a rejected credential is shown at once and nothing is stored. To change one field later, fill in only that field; a blank field keeps its stored value.

AI summaries stay off. Do not turn them on during the first run.

## 3. What a good first sync looks like
- Right after you press the button the card says **Syncing…**; within a few seconds to a minute it says **Connected**.
- The card shows each field as "set · ends xxxx" and never the value.
- Today, Week and Month show items from the sources you connected: assignments and planner items from Canvas, events from Apple Calendar and the LearningSuite feeds, owed replies from Gmail, one forecast line per day from Weather.
- Nothing shows **Error**. **Reconnect needed** on Gmail seven days after you connected it is expected (Google's rule for an unverified client, [gmail-setup.md](gmail-setup.md)).

To check it without reading the screen, or to send a status to someone, run:
```sh
bash scripts/report-state.sh
```
It prints, per source, the sync status, a redacted message, the last 4 characters of each key (or "none") and an event count, plus the git commit and the app version. It reads only the app's own redacted answers and is safe to paste. It prints no secret, no URL and no event title ([decision 0078](decisions/0078-smoke-and-report-scripts-and-what-they-never-print.md)).

## 4. Known risk: Canvas says "Reconnect needed" although the token is valid
What is known (decisions [0041](decisions/0041-canvas-skips-a-course-it-cannot-read.md) and [0046](decisions/0046-a-skipped-canvas-course-loses-only-its-assignments.md)): Canvas can answer 401 when the token is fine but the user may not read something, for example an unpublished or locked course.
- A 401 on one course's **assignments** only skips that course's assignments. The card stays **Connected**.
- A 401 on the user, the course list, the planner or the calendar call is treated as an expired token, so the card shows **Reconnect needed**.
- Not confirmed (it is the "revisit when" of 0046): the calendar call is sent the ids of every active course, including the skipped ones. If Canvas answers 401 to the whole call when one id is a course you cannot read, the whole Canvas sync fails and shows **Reconnect needed** with a token that still works. Neither the Canvas documentation nor our tests say what Canvas does.

What to do if you see it:
1. Do not create a new token and do not paste the old one anywhere. Look in Canvas under Approved Integrations: the token should be listed and not expired. If it is gone or expired, it really is expired: create a new one and enter it in Settings.
2. If the token is listed and valid, press the Canvas card's button once more (leave the fields blank) to rule out a passing failure.
3. Still **Reconnect needed**: run `bash scripts/report-state.sh` and send the output, with the date and the name of any course you know is unpublished or locked.
4. Stop there. The planned fix (0046) is to leave skipped courses' ids out of the planner and calendar requests. That is a code change for the project manager to decide, not a setting you can change.

The other sources keep syncing while Canvas shows Reconnect.

## 5. LearningSuite connects but shows 0 items
Run the diagnosis. It reads the feed links already stored on this computer (you paste nothing), downloads each feed once and prints only counts, categories and dates: never a link, a title, a description or a location, so the whole output is safe to paste ([decision 0140](decisions/0140-learningsuite-diagnosis-is-a-counts-only-subcommand.md)).
```sh
uv run command-center diagnose learningsuite
```
It prints, per feed, the HTTP status class (2xx/3xx/4xx/5xx), the content kind (`calendar`, `html`, `text`, `json`, `other`, `missing`), the size in bytes, how many VEVENT and VTODO items the feed holds, how many have a start or due date, the earliest and latest date, and where the events fall relative to the **sync window** (from 14 days before today up to, not including, 60 days after it, by UTC dates: the same window a sync uses): inside, before, after, undated, cancelled, or dropped because a recurrence rule could not be expanded. The last line is the conclusion:

| Conclusion line | What it means and what to do |
|---|---|
| `no feed URLs are stored` | LearningSuite is not connected. Paste the links in Settings. |
| `N of M feeds could not be read` | Read each feed's `Problem:` line. `HTTP 4xx` with content `html` is usually a login page or a link that expired or was copied wrongly: copy the course's link again in LearningSuite and paste it in Settings. `5xx` or `could not be reached`: try again later. A sync keeps nothing from a run in which any feed fails. |
| `feed contains no VEVENT or VTODO` | Every feed is an empty calendar. Nothing to fix here: check the courses' schedules in LearningSuite. |
| `feed contains only VTODO items` | The feed lists tasks, and Command Center reads events only, so it returns 0. This is a gap in the app, not in your setup: report it to the project manager with the output. |
| `all events are before the window` / `after the window` / `outside the window` | The feeds work but every event is older than 14 days or 60 or more days away (for example a past semester). Items show once a date falls in the window. |
| `all events have no start time` | The events carry no start date, so they cannot be placed on a day and are left out. |
| `all events are cancelled` | Every event is marked cancelled and is skipped. |
| `some recurring events could not be expanded (N)` | A repeating event has a rule the app cannot read. A sync fails on it and keeps nothing from that feed, so this comes before every other answer. Report it with the output. |
| `N events fall inside the window: a sync should return them` | The feed is fine. Press the LearningSuite card's button to sync again; if it still shows 0, run `bash scripts/report-state.sh` and send both outputs. |

When a sync keeps nothing the app also writes one counts-only line to its log, for example `Synced 0 items: 3 feeds, 12 events in the feeds, 0 inside the window`; the card itself does not show it ([decision 0141](decisions/0141-zero-item-feed-counts-are-logged-not-shown-on-the-card.md)).

## 6. If something else is wrong
- **Error** on a source: the card's text is already redacted; run `scripts/report-state.sh` and send the output.
- Nothing is listening on 8765: another copy is running, or the server did not start; the terminal that runs `uv run command-center` says why.
- The distributed (Docker) stack has its own guide and a smoke test: [distributed-mode.md](distributed-mode.md).
- Phone: [mobile.md](mobile.md). General operations: [runbook.md](runbook.md).
