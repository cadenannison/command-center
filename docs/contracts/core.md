# Contract: core

Pure domain layer. Imports nothing in the app and no infrastructure library (see docs/MAP.md).
No I/O, clock, randomness, environment or globals; time, randomness and ids come in as parameters.

## Public exports (module: names)
- `ports`: `Clock`, `Rng`, `IdSource`, `SourceAdapter`, `SecretStore`, `EventStore` (all Protocols).
- `schema`: `Event`, `EventKind`, `ValidationResult`, `SecretStatus`, `secret_status`, `event_id`. `ValidationResult.updated_creds` holds refreshed tokens and is excluded from `repr`/`str`.
- `errors`: `SourceError` (base), `AuthExpired`, `TransientError`, `FatalError`, `SecretStoreError`.
- `scoring`: `urgency`.
- `redact`: `redact`, `trim`.
- `windows`: `TimeWindow`, `day_window`, `week_window`, `month_window`.
- `urlcheck`: `require_https_public`.

## Behaviour
- `ports.py` defines `Clock` (`now() -> datetime`, timezone-aware), `Rng` (`random() -> float` in [0,1)) and `IdSource` (`new_id() -> str`) as Protocols. Everything time-, random- or id-dependent takes one as a parameter.
- Reason: determinism. Any core function is reproducible from its inputs, so tests need no patching.

### Event (`schema.py`)
Frozen pydantic model: `id`, `user_id` (default `"local"`), `source`, `kind` (`event|assignment|email|weather`), `title`, `start`, `end`, `due` (all optional), `urgency` (int 0-100, default 0), `link`, `status`, `raw` (dict), `fetched_at`. Every datetime is timezone-aware; naive values are rejected. `event_id(source, source_id)` is `sha256(source + NUL + source_id).hexdigest()[:32]`; ids are persisted, so the algorithm never changes. `status` is a free string; scoring recognises `"done"` (assignments) and `"overdue"` / `"owed"` (emails).

### Ports
- `SourceAdapter`: `name`; `async validate(creds: Mapping[str, str]) -> ValidationResult(ok, message, updated_creds | None)`; `async fetch(creds, window) -> list[Event]`. Failures are raised as `AuthExpired` (reconnect), `TransientError` (retry later) or `FatalError` (do not retry), all subclasses of `SourceError`.
- `SecretStore` (sync), keyed per field: `set(source, key, value)`, `get(source) -> Mapping[str, str]` (empty if none), `status(source) -> Mapping[str, SecretStatus]` (empty if none), `delete(source)` (removes ALL keys of the source; not an error if none). One string value per (user, source, key). `status` never reveals more than the last 4 characters: `SecretStatus.last4` is `str | None` and is `None` for an unset secret and for any value shorter than 8 characters (7 characters gives `None`, 8 gives the last 4). `secret_status(value)` in `schema` is the one rule stores use. Decision: docs/decisions/0010.
- `EventStore` (sync): `upsert(events) -> int` is idempotent by `(user_id, id)` and returns the number of distinct events written; an event whose `user_id` differs from the argument is a `ValueError`. `query(window, kinds=None) -> list[Event]` returns events whose time falls in the half-open window, ordered by time then id. An event's time is `start` (else `due`); if `end` is after that time the event is a span and matches when it overlaps the window, otherwise it is a point at that time; undated events never match (an `end` alone does not date an event). `replace(source, window, events) -> int` runs in one transaction: it deletes the user's events of `source` that match `window` under the same rules as `query` (so undated events are never deleted), then upserts `events`; on failure the old events remain, and stored events outside `window` are not pruned. Call it only after a fully successful fetch, never with a partial result, because every stored event of the source in the window that is missing from `events` is deleted. An event whose `user_id` differs from the argument, or whose `source` differs from `source`, is a `ValueError` and nothing changes. It returns the number of distinct events written. `delete_source(source) -> int` deletes every event of `source` for the user, dated or undated, and returns the number deleted (none stored is not an error).
- `SecretStoreError` is raised by a `SecretStore` when the keychain cannot be used; its message says why, never carries a secret value, and it is not a `SourceError` (it is not a source failure).
- Every store method takes a keyword `user_id="local"`.

### Urgency scoring (`scoring.py`)
`urgency(event, now) -> int` is deterministic and always 0-100; it ignores the stored `event.urgency`. Time to due/start is computed on UTC instants, so DST shifts count as real elapsed time (aware datetimes sharing one tzinfo otherwise subtract by wall clock). "Today" for events is the calendar date in `now`'s timezone, so pass `now` in the user's timezone. A naive `now` (no `tzinfo`, or a `tzinfo` whose `utcoffset` is `None`) is a `ValueError` for every kind, because `astimezone` would silently read the host's timezone.

| Kind | Condition (first match wins) | Score |
|---|---|---|
| assignment | status `done` | 0 |
| assignment | due before now (overdue, not done) | 100 |
| assignment | due within 24h | 90 |
| assignment | due within 72h | 70 |
| assignment | due within 7 days | 40 |
| assignment | later, or no due date | 10 |
| event | ended: `end < now`, or `start < now` with no `end` | 0 |
| event | otherwise no `start` | 10 |
| event | ongoing (`end >= now`) or `start` within 2h of now, and `end - start` under 24h or no `end` | 60 |
| event | ongoing or `start` within 2h of now, and `end - start` of 24h or more | 40 |
| event | start later today | 40 |
| event | start after today | 10 |
| email | status `overdue` | 75 |
| email | status `owed` | 50 |
| email | any other status | 5 |
| weather | always | 0 |

Boundaries are inclusive on the upper side (exactly 24h away scores 90). Event boundaries, all compared as UTC instants: `end == now` is still ongoing; `start == now` with no `end` counts as starting now (60); `start - now == 2h` scores 60; a span of exactly 24h scores 40 while ongoing or imminent. A 24h+ span that starts later today still scores 40 and one starting after today 10. An event with an `end` before now is 0 even when it has no `start`. An assignment's score never rises as its due date moves later.

### Redaction (`redact.py`)
`redact(text)` replaces any whitespace-delimited token containing `@` (with text on both sides) by `[email]`, then every group of digits joined by whitespace, `-`, `.`, `(` or `)` with 6 or more digits in total by `[number]` (`801-555-1234`, `(801) 555 1234`, `4111 1111 1111 1111`, `20261107`). Groups with fewer than 6 digits stay (`CS 101`, `room 12-34`). Exception: an ISO date `YYYY-MM-DD` (ASCII digits, month 01-12, day 01-31) stays only when nothing is attached to it: it must be bounded by whitespace or the edge of its digit group, so `20261107`, `2026-11-07-1234`, `2026-11-07.5` and `5-2026-11-07` are redacted, while `due 2026-11-07` and `2026-11-07 8015551234` keep the date. Digits on the far side of a whitespace-delimited date are judged separately. Matching is linear in the input length (the email pattern is anchored at a token start), so long adversarial inputs are safe. It is idempotent and does not touch surrounding words or the `[email]` / `[number]` markers.

Over-redaction is deliberate: `1 2 3 4 5 6`, `1.2.3.4.5.6` or `1 000 000` become `[number]`, because a false positive costs a word of context and a miss leaks data. `redact` runs BEFORE `trim`, never after, so trimming cannot leave a partial number. `trim(text, limit)` strips, then cuts to at most `limit` characters ending in an ellipsis; `limit < 0` is a `ValueError`. Email bodies never enter core; only titles, due dates and trimmed subjects. Decision: docs/decisions/0011.

### Windows (`windows.py`)
`TimeWindow(start, end)` is a frozen half-open interval of timezone-aware instants, `end` after `start`, with `contains(instant)`, which raises `ValueError` for a naive `instant` (no `tzinfo`, or a `tzinfo` whose `utcoffset` is `None`) rather than reading the host's timezone. `day_window`, `week_window` (Monday start) and `month_window` take a `date` and a `tzinfo` and are built from local midnight of calendar dates, so DST days are 23 or 25 hours and adjacent windows are contiguous. When a zone skips local midnight, the window starts at the first valid moment. Compare window edges in UTC (`.astimezone(UTC)`); datetimes sharing one tzinfo compare by wall clock.

### URL check (`urlcheck.py`)
`require_https_public(url) -> str` returns the URL unchanged or raises `ValueError`. Rejected: non-https, no host, userinfo, whitespace or control characters, `localhost` and `*.localhost` / `*.local`, any literal IP that is not globally routable (`is_global` is false: private, loopback, link-local, CGNAT `100.64.0.0/10`, 6to4, unspecified, ...) plus multicast and site-local `fec0::/10`; the IPv4 inside IPv4-mapped, NAT64 `64:ff9b::/96` and IPv4-compatible `::/96` addresses is checked instead; numeric host spellings such as `2130706433` or `0x7f000001`; and non-IP hostnames containing anything other than ASCII letters, digits, `-` and `.` (so backslashes, percent-escapes, full-width digits and unicode names are refused; callers pass IDNs as punycode). Error messages never echo the URL, host or userinfo (nor the parser's own message, which embeds the netloc), so they are safe to log; the `ValueError` for an unparseable URL is raised outside the `except` block, so both `__cause__` and `__context__` are `None` and the parser's own message (which quotes the netloc) is never reachable from it. It checks the literal host only; core does no DNS, so callers still need to guard against names that resolve to private addresses.

## Planned (not built yet)
- Schema for tasks, messages and source status beyond `Event`.
- Scoring tunables passed in as data.
