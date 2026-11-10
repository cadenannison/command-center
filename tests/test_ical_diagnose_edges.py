"""Feed diagnosis edge cases: overrides, zones, a failed recurrence beside a good item, errors."""

import pytest
import respx

from command_center.adapters import ical_diagnose
from command_center.adapters.ical_diagnose import diagnose_feeds
from command_center.adapters.ical_diagnose_report import FeedReport, conclusion, render
from ical_diagnose_support import (
    FEED_1,
    PRIVATE,
    calendar,
    feed,
    resolves_to_public,
    vevent,
)
from ics_support import DENVER, WINDOW

IN_WINDOW = "DTSTART:20261105T100000Z"
AFTER = "DTSTART:20270301T100000Z"
DENVER_ZONE = """BEGIN:VTIMEZONE
TZID:America/Denver
BEGIN:STANDARD
DTSTART:19701101T020000
TZOFFSETFROM:-0600
TZOFFSETTO:-0700
TZNAME:MST
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700308T020000
TZOFFSETFROM:-0700
TZOFFSETTO:-0600
TZNAME:MDT
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
END:VTIMEZONE""".replace("\n", "\r\n")


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    resolves_to_public(monkeypatch)


async def one(body: str) -> tuple[FeedReport, str]:
    with respx.mock:
        respx.get(FEED_1).mock(feed(body))
        reports = await diagnose_feeds([FEED_1], DENVER, WINDOW)
    return reports[0], render(reports, WINDOW)


async def test_an_event_with_a_tzid_and_its_vtimezone_is_placed_in_the_window() -> None:
    event = vevent("a", "DTSTART;TZID=America/Denver:20261105T100000")
    report, _ = await one(calendar(DENVER_ZONE, event))
    assert (report.events, report.inside) == (1, 1)


async def test_an_override_that_moves_the_only_instance_out_of_the_window_is_not_inside() -> None:
    master = vevent("a", IN_WINDOW, "RRULE:FREQ=DAILY;COUNT=1")
    moved = vevent("a", AFTER, "RECURRENCE-ID:20261105T100000Z")
    report, text = await one(calendar(master, moved))
    assert (report.events, report.inside) == (2, 0)
    assert all(secret not in text for secret in PRIVATE)


async def test_an_override_that_cancels_the_only_instance_is_not_inside() -> None:
    master = vevent("a", IN_WINDOW, "RRULE:FREQ=DAILY;COUNT=1")
    cancelled = vevent("a", IN_WINDOW, "RECURRENCE-ID:20261105T100000Z", "STATUS:CANCELLED")
    report, _ = await one(calendar(master, cancelled))
    assert (report.events, report.inside) == (2, 0)


async def test_a_recurrence_error_beside_a_good_event_says_the_sync_fails() -> None:
    body = calendar(vevent("a", IN_WINDOW), vevent("b", IN_WINDOW, "RRULE:FREQ=BOGUS"))
    report, text = await one(body)
    assert (report.inside, report.dropped) == (1, 1)
    assert text.splitlines()[-1] == (
        "Conclusion: some recurring events could not be expanded (1): "
        "a sync fails on them and keeps nothing from that feed"
    )
    assert conclusion([report]).startswith("some recurring events")


async def test_a_host_that_resolves_to_a_private_address_is_not_called_a_bad_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolves_to_public(monkeypatch, "10.0.0.5")
    reports = await diagnose_feeds([FEED_1], DENVER, WINDOW)
    assert reports[0].problem == "the host is not a public address or could not be resolved"


async def test_an_unexpected_error_becomes_a_fixed_phrase_without_its_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(_url: str) -> object:
        msg = f"leaked {FEED_1}"
        raise RuntimeError(msg)

    monkeypatch.setattr(ical_diagnose, "_probe", boom)
    reports = await diagnose_feeds([FEED_1], DENVER, WINDOW)
    text = render(reports, WINDOW)
    assert reports[0].problem == "an unexpected error stopped the check"
    assert all(secret not in text for secret in PRIVATE)
