# 0030. iCal feed items are `event`, not `assignment`

Status: accepted

Context: Task 2b left "[KEEP ONE]" between two mappings for LearningSuite feed items: kind `assignment` (due = end of that local day, status "open") or kind `event` with start/end from the feed. The human chose `event` when asked. Decision 0005 supports it: the only source it cites says the feeds carry "schedule items" as all-day events and does not say they are assignment due dates.
Decision: `ical_feed.py` and `caldav_apple.py` both emit kind `event` with `start`/`end` from the item. An all-day date becomes local midnight to the next local midnight (in the tzinfo the constructor was given); a floating time is placed in that tzinfo; an item with no end is a point (`end` None). `due` and `status` of the feed are not set from the feed; `status` carries the item's own STATUS (lowercased) when it has one.
Alternative: kind `assignment` with `due` at 23:59:59.999999 local and status "open". Not taken because every schedule item, class sessions included, would be scored as a deadline, and nothing in the feed tells assignments from other items.
Why: Not inventing a deadline the source never stated; urgency scoring stays honest.
Where: `src/command_center/adapters/ical_events.py` (`_to_event`), `tests/test_ical_feed.py`, `tests/test_ical_events.py`.
Revisit when: A feed is shown to mark assignment deadlines in a recognisable way (a category or a title pattern); map those to `assignment` in `ical_events.py` then, with a new record superseding this one.
Sources (checked 2026-11-07): docs/decisions/0005-learningsuite.md.
