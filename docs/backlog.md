# Backlog

Features and changes we want, collected while testing. An item here is an idea, not a commitment: nothing
in this file changes the code or a contract. When an item is built, remove it from here and record the
choice in [decisions/](decisions/) as AGENTS.md requires.

Add an item as you find it: a title, why it matters, what it would take, and its status.
Status is one of `proposed` (written down, not yet decided), `accepted` (we will build it) or `blocked`.

## Weather: set the location by city name
- Status: accepted; the search API is built (`GET /v1/geocode`, decisions 0180-0182), the form is not
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
  ## Hyperlinks to all assignments
  

## Chat: save conversations
- Status: proposed
- Why: chats are in memory only (20 turns, 20 conversations) and are forgotten on restart; the card allowed a "save chats" setting, default off (decision 0166).
- Idea: a conversation table in the ledger store, a `chat.save` app setting (default off), and a delete that clears both memory and disk. No UI control yet.
- Touches: `storage/`, `services/chat.py`, `core/ports.py` (a store port), the chat contracts.

## Summaries and chat: unify the providers
- Status: proposed
- Why: `SummaryProvider` and `ChatProvider` are separate ports with separate adapters (Ollama twice, Gemini twice) (decision 0167).
- Idea: build the summary providers on `ChatProvider` (one prompt in, one text out) once both are stable, keeping the summary tests unchanged.
- Touches: `adapters/summary_ollama.py`, `adapters/summary_gemini.py`, `services/summary.py`, `core/ports.py`.

## Check-off: retry once on a Postgres deadlock
- Status: proposed (decision 0233: the sync's locking stays as it is)
- Why: on Postgres a check-off on an item stored outside a running sync's window can deadlock with that sync; the sync is redelivered, but the check-off shows a server error (`_tolerating_concurrent_writes` catches only `IntegrityError`).
- Idea: retry the check-off once when Postgres reports a deadlock (a named failure class, a cap of one retry, a logged reason), and add a two-connection test for the interleaving that runs in the CI integration job, where Postgres is available.
- Touches: `storage/sqlite_items.py` (`_tolerating_concurrent_writes`), a new test beside `tests/test_ledger_races.py`.

## Chat: optional proxy and private CA support
- Status: proposed (decision 0225)
- Why: chat calls ignore `HTTP_PROXY`, the system proxy and `SSL_CERT_FILE` (`trust_env=False`), so a user behind a mandatory proxy or a private CA cannot reach a public https provider.
- Idea: an opt-in `CC_CHAT_TRUST_ENV` that turns `trust_env` back on for chat, off by default, with the proxy still unable to bypass the address checks it was added to protect.
- Touches: `adapters/chat_http.py` (`post_json`), `config.py`, `app.py`, `docs/contracts/adapters.md`, a new decision.

## Web: move the inline htmx scripts to a static file if a CSP is added
- Status: proposed (decision 0212)
- Why: the global error listener is inline in `base.html`, and the chat page's New chat button carries inline `hx-on` handlers (decision 0203); a Content-Security-Policy would block both.
- Idea: move the listener to `web/static/cc.js` loaded after htmx and replace the `hx-on` handlers with a listener there; `test_pages_load_nothing_from_outside` then lists the second script.
- Touches: `templates/base.html`, `templates/_htmx_errors.js`, `templates/_chat_parts.html`, `tests/test_web_pages.py` (the task card must say `tests: modify`).

## Pairing: purge superseded refresh rows after the reuse-detection window (about 96 rows a day per device)
- Status: proposed (second review, finding 10; reuse detection needs superseded rows for a window, so purge after that window)
- Why: every refresh rotates the device's refresh credential and keeps the superseded row so a reused token can be detected, so rows pile up at about 96 a day per device (one refresh before each 15-minute access token ends).
- Idea: delete a superseded refresh row once the reuse-detection window has passed, in the same transaction as a refresh or in a periodic purge, with the window and the batch size named in the code; a test shows a reuse inside the window still revokes the device and a reuse after it is only refused.
- Touches: `storage/sqlite_devices.py`, `services/pairing.py`, `docs/contracts/storage.md`, a new decision.

## Gemini key check: catch unknown exceptions and close the client safely
- Status: proposed
- Why: `GeminiIntegration.validate` re-raises an exception it does not recognise (its text may hold the key, and `SettingsService._check` catches only `AuthExpired`, `TransientError` and `FatalError`, so it becomes a 500), and its `finally` closes the client with a bare `aclose()`/`close()` rather than `_close`.
- Idea: end `validate` with a fixed-text `FatalError` that logs only the class name, and close through `_close`; a test with an arbitrary exception carrying a needle. See decision 0245.

## Schema guard: runtime check that every table in the schema comes from the ledger base
- Status: proposed (final review, finding 5; decisions 0232, 0247)
- Why: the static guard in `tests/test_schema_guard.py` reads source text, so it misses SQL in strings, `.sql` files, `string.Template`, `CREATE VIRTUAL TABLE` and `CREATE TEMP TABLE`, `ALTER ... RENAME`, and tables found through `Inspector` reflection. A table made any of those ways would not be created through the ledger base and nothing would fail.
- Idea: a runtime check on a freshly built database that every table in the schema (what `Inspector` reports) comes from the ledger base metadata, and fails naming the extra or missing ones; a new test runs it against the real storage setup.
- Touches: `storage/` (where the ledger base and schema are built), a new test beside `tests/test_schema_guard.py`, `docs/contracts/storage.md`, a new decision.

## Split core/redact.py into rule modules
- Status: proposed (task R3; decision 0280 "Revisit when")
- Why: `core/redact.py` is about 400 lines; the aim is 300 (`.claude/rules/style.md`).
- Idea: split the rules into modules (urls and emails, tokens and keys, digit groups and exemptions, codes, IPv6) behind the same `redact()`; the rule order and the idempotence guards (decisions 0261, 0283) must stay as they are.

## test:for: a flag that prints every indirect test
- Status: proposed (decision 0285)
- Why: `mise run test:for` caps indirect output at 15 lines and prints "+N more", so some tests are hidden and the command cannot list them (for `core/redact.py` it hides 78).
- Idea: a flag (for example `--all`) that prints every indirect test, one per line, so an agent can run them all; the default output stays capped.
- Touches: `scripts/tests_for.py`, `tests/test_tests_for_indirect.py` and `tests/test_tests_for_limits.py` (the task card must say `tests: modify`), the `test:for` line in `AGENTS.md`, a new decision.
