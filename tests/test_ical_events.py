"""iCalendar text to Events: recurrence, all-day, floating and DST, against .ics fixtures."""

from datetime import UTC, datetime, tzinfo

import pytest

from builders import NOW
from command_center.adapters.ical_events import NO_TITLE, events_in_window, parse_calendar
from command_center.core.schema import Event
from command_center.core.windows import TimeWindow
from ics_support import DENVER, WINDOW, load, utc


def read(
    name: str, *, tz: tzinfo = DENVER, window: TimeWindow = WINDOW, scope: str = "s"
) -> list[Event]:
    return events_in_window(
        parse_calendar(load(name)),
        source="test",
        scope=scope,
        tz=tz,
        window=window,
        fetched_at=NOW,
    )


def spans(events: list[Event]) -> list[tuple[str, datetime, datetime | None]]:
    ordered = sorted(events, key=lambda e: e.start or NOW)
    return [
        (e.title, e.start.astimezone(UTC), e.end and e.end.astimezone(UTC))
        for e in ordered
        if e.start
    ]


def test_recurrence_is_expanded_with_exdate_and_override() -> None:
    found = spans(read("recurring.ics"))
    assert [(title, start) for title, start, _ in found] == [
        ("Standup", utc(2026, 10, 31, 15)),  # MDT, UTC-6
        ("Standup", utc(2026, 11, 1, 16)),  # MST, UTC-7: still 09:00 on the wall clock
        ("Standup (moved)", utc(2026, 11, 3, 21)),  # RECURRENCE-ID replaced the 09:00 one
        ("Standup", utc(2026, 11, 4, 16)),
    ]
    assert found[0][2] == utc(2026, 10, 31, 15, 30)


def test_recurring_instances_get_distinct_stable_ids() -> None:
    first, second = read("recurring.ics"), read("recurring.ics")
    ids = [event.id for event in first]
    assert len(set(ids)) == len(ids) == 4
    assert sorted(ids) == sorted(event.id for event in second)


def test_all_day_items_span_local_midnights_including_the_25_hour_day() -> None:
    found = {title: (start, end) for title, start, end in spans(read("allday.ics"))}
    assert found["Veterans Day break"] == (utc(2026, 11, 10, 7), utc(2026, 11, 11, 7))
    assert found["Retreat"] == (utc(2026, 11, 12, 7), utc(2026, 11, 14, 7))  # DTEND is exclusive
    assert found["Clocks go back"] == (utc(2026, 11, 1, 6), utc(2026, 11, 2, 7))


def test_floating_times_are_placed_in_the_given_zone() -> None:
    found = {title: (start, end) for title, start, end in spans(read("floating.ics"))}
    assert found["Floating morning"] == (utc(2026, 11, 10, 16), utc(2026, 11, 10, 17))
    assert found["Floating late"] == (utc(2026, 11, 11, 6, 30), utc(2026, 11, 11, 7, 30))


def test_floating_times_follow_the_zone_that_is_passed() -> None:
    found = {title: start for title, start, _ in spans(read("floating.ics", tz=UTC))}
    assert found["Floating morning"] == utc(2026, 11, 10, 9)


def test_every_event_is_timezone_aware_kind_event_with_urgency_zero() -> None:
    events = [
        e for name in ("recurring", "allday", "floating", "edges") for e in read(f"{name}.ics")
    ]
    assert events
    for event in events:
        assert event.kind == "event"
        assert event.urgency == 0
        assert event.start is not None
        assert event.start.utcoffset() is not None
        assert event.fetched_at == NOW


def test_edges_cancelled_and_outside_items_are_dropped() -> None:
    titles = {e.title for e in read("edges.ics")}
    assert titles == {"Overnight", "Point in time", NO_TITLE}


def test_point_item_has_no_end_status_and_https_link() -> None:
    (point,) = [e for e in read("edges.ics") if e.title == "Point in time"]
    assert (point.end, point.status, point.link) == (
        None,
        "tentative",
        "https://example.com/item/1",
    )


def test_non_http_link_is_dropped() -> None:
    (item,) = [e for e in read("edges.ics") if e.title == NO_TITLE]
    assert item.link is None


def test_raw_holds_public_fields_and_the_caller_extras() -> None:
    events = events_in_window(
        parse_calendar(load("edges.ics")),
        source="test",
        scope="s",
        tz=DENVER,
        window=WINDOW,
        fetched_at=NOW,
        extra_raw={"calendar": "Work"},
    )
    (point,) = [e for e in events if e.title == "Point in time"]
    assert point.raw == {"uid": "point@fake", "location": None, "calendar": "Work"}


def test_span_that_began_before_the_window_is_kept_by_overlap() -> None:
    window = TimeWindow(
        start=utc(2026, 11, 10, 6), end=utc(2026, 11, 10, 20)
    )  # overnight ends 09:00Z
    assert "Overnight" in {e.title for e in read("edges.ics", window=window)}


def test_span_ending_exactly_at_window_start_is_excluded() -> None:
    window = TimeWindow(start=utc(2026, 11, 10, 9), end=utc(2026, 11, 10, 20))
    assert "Overnight" not in {e.title for e in read("edges.ics", window=window)}


def test_point_follows_the_half_open_window() -> None:
    noon = utc(2026, 11, 10, 19)  # 12:00 MST
    at_end = TimeWindow(start=utc(2026, 11, 10, 0), end=noon)
    at_start = TimeWindow(start=noon, end=utc(2026, 11, 11, 0))
    assert "Point in time" not in {e.title for e in read("edges.ics", window=at_end)}
    assert "Point in time" in {e.title for e in read("edges.ics", window=at_start)}


def test_scope_separates_the_same_uid_in_two_places() -> None:
    first = {e.id for e in read("floating.ics", scope="1")}
    second = {e.id for e in read("floating.ics", scope="2")}
    assert first.isdisjoint(second)


def test_item_without_dtstart_is_skipped() -> None:
    text = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\nUID:a\nSUMMARY:No start\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    events = events_in_window(
        parse_calendar(text), source="t", scope="s", tz=DENVER, window=WINDOW, fetched_at=NOW
    )
    assert events == []


@pytest.mark.parametrize(
    "text", ["<html>secret-token-123</html>", "", "BEGIN:VEVENT\nEND:VEVENT\n"]
)
def test_non_calendar_text_is_a_value_error_that_does_not_quote_it(text: str) -> None:
    with pytest.raises(ValueError, match="Not an iCalendar") as caught:
        parse_calendar(text)
    assert "secret-token-123" not in str(caught.value)


def test_unexpandable_rule_is_a_value_error() -> None:
    text = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\nUID:a\nDTSTAMP:20261001T000000Z\n"
        "DTSTART:20261110T090000\nRRULE:FREQ=NOPE\nSUMMARY:Bad rule\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    with pytest.raises(ValueError, match="recurrence rules"):
        events_in_window(
            parse_calendar(text), source="t", scope="s", tz=DENVER, window=WINDOW, fetched_at=NOW
        )


def test_unparseable_link_is_dropped() -> None:
    text = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\nUID:a\nDTSTAMP:20261001T000000Z\n"
        "DTSTART:20261110T090000\nURL:http://[::1\nSUMMARY:Odd link\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    (item,) = events_in_window(
        parse_calendar(text), source="t", scope="s", tz=DENVER, window=WINDOW, fetched_at=NOW
    )
    assert item.link is None
