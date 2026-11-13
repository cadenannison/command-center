# 0399. Snooze presets are computed on the server in the user's local day

Status: accepted

Context: Snooze needs an end time. Clients should not each work out "tomorrow morning" in their own zone and DST.
Decision: `POST /v1/items/{id}/snooze` takes `{"preset": "later_today" | "tomorrow_morning" | "next_week"}` and the server computes the end in the configured timezone (`core/snooze.py`, pure; `now` and the zone come in). later_today is three elapsed hours on, or 23:59 local when that would pass midnight, or the start of tomorrow when under a minute of today is left. tomorrow_morning is 08:00 local tomorrow. next_week is 08:00 local on the next Monday (a week on when today is Monday). A snooze ends at its instant: from then on the item is back. No custom time in this version.
Alternative: The client sends an instant (rejected for this card: every client repeats the zone and DST math, and the card asks for presets). A fixed "later today" clock time such as 17:00 (rejected: useless after 17:00).
Reason: The server already owns the user's timezone, so one implementation serves the web, the phone and curl.
Consequences: An invalid preset is 422. The response carries `snoozed_until` as an instant.
Where: `core/snooze.py`, `services/items.py`, `api/items.py`; `tests/test_snooze_presets.py`.
Revisit when: a custom time is added, or the 08:00 morning should be a setting.
