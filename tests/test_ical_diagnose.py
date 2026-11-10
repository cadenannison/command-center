"""Feed diagnosis: fake feeds through respx; only counts, categories and dates come out."""

import logging

import httpx
import pytest
import respx

from builders import NOW
from command_center.adapters.ical_diagnose import content_kind, diagnose_feeds, status_class
from command_center.adapters.ical_diagnose_report import FeedReport, conclusion, render
from command_center.adapters.ical_feed import IcalFeedAdapter, zero_items_message
from ical_diagnose_support import (
    FEED_1,
    FEED_2,
    PRIVATE,
    calendar,
    feed,
    resolves_to_public,
    vevent,
    vtodo,
)
from ics_support import DENVER, WINDOW

IN_WINDOW = "DTSTART:20261105T100000Z"
BEFORE = "DTSTART:20260301T100000Z"
AFTER = "DTSTART:20270301T100000Z"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    resolves_to_public(monkeypatch)


async def run(*urls: str) -> tuple[list[FeedReport], str]:
    reports = await diagnose_feeds(list(urls), DENVER, WINDOW)
    return reports, render(reports, WINDOW)


def assert_private_text_absent(text: str) -> None:
    for secret in PRIVATE:
        assert secret not in text


@respx.mock
async def test_events_all_outside_the_window_are_counted_before_and_after() -> None:
    body = calendar(vevent("a", BEFORE), vevent("b", BEFORE), vevent("c", AFTER))
    respx.get(FEED_1).mock(feed(body))
    reports, text = await run(FEED_1)
    report = reports[0]
    assert (report.events, report.inside, report.before, report.after) == (3, 0, 2, 1)
    assert (report.status_class, report.content_kind) == ("2xx", "calendar")
    assert report.size_bytes == len(body.encode())
    assert (str(report.earliest), str(report.latest)) == ("2026-03-01", "2027-03-01")
    assert (
        conclusion(reports) == "all events are outside the window (some before it, some after it)"
    )
    assert "Feed 1: HTTP 2xx, content-type calendar" in text
    assert_private_text_absent(text)


@respx.mock
async def test_events_all_before_the_window_say_so() -> None:
    respx.get(FEED_1).mock(feed(calendar(vevent("a", BEFORE))))
    reports, text = await run(FEED_1)
    assert conclusion(reports) == "all events are before the window"
    assert text.endswith("Conclusion: all events are before the window")


@respx.mock
async def test_an_empty_calendar_has_no_vevent_or_vtodo() -> None:
    respx.get(FEED_1).mock(feed(calendar()))
    reports, text = await run(FEED_1)
    assert (reports[0].events, reports[0].todos, reports[0].earliest) == (0, 0, None)
    assert conclusion(reports) == "feed contains no VEVENT or VTODO"
    assert "Dates (start or due): none" in text
    assert_private_text_absent(text)


@respx.mock
async def test_a_vtodo_only_feed_is_not_read_by_the_sync() -> None:
    body = calendar(
        vtodo("a", "DUE:20261106T100000Z"), vtodo("b", "DUE:20260101T100000Z"), vtodo("c")
    )
    respx.get(FEED_1).mock(feed(body))
    reports, text = await run(FEED_1)
    report = reports[0]
    assert (report.events, report.todos, report.dated) == (0, 3, 2)
    assert (report.todos_dated, report.todos_inside) == (2, 1)
    assert (str(report.earliest), str(report.latest)) == ("2026-01-01", "2026-11-06")
    assert conclusion(reports).startswith("feed contains only VTODO items")
    assert_private_text_absent(text)


@respx.mock
async def test_undated_entries_are_counted_and_never_placed_in_the_window() -> None:
    respx.get(FEED_1).mock(feed(calendar(vevent("a"), vevent("b"))))
    reports, text = await run(FEED_1)
    assert (reports[0].events, reports[0].undated, reports[0].dated) == (2, 2, 0)
    assert (
        conclusion(reports) == "all events have no start time, so none can be placed in the window"
    )
    assert_private_text_absent(text)


@respx.mock
async def test_a_cancelled_event_and_a_recurrence_error_are_their_own_categories() -> None:
    body = calendar(
        vevent("a", IN_WINDOW, "STATUS:CANCELLED"),
        vevent("b", IN_WINDOW, "RRULE:FREQ=BOGUS"),
        vevent("c", IN_WINDOW),
    )
    respx.get(FEED_1).mock(feed(body))
    reports, text = await run(FEED_1)
    report = reports[0]
    assert (report.cancelled, report.dropped, report.inside) == (1, 1, 1)
    assert "1 cancelled, 1 dropped (recurrence errors)" in text
    assert_private_text_absent(text)


@respx.mock
async def test_events_inside_the_window_are_counted_across_feeds() -> None:
    respx.get(FEED_1).mock(feed(calendar(vevent("a", IN_WINDOW), vevent("b", BEFORE))))
    respx.get(FEED_2).mock(feed(calendar(vevent("c", IN_WINDOW))))
    reports, text = await run(FEED_1, FEED_2)
    assert [report.inside for report in reports] == [1, 1]
    assert conclusion(reports) == "2 events fall inside the window: a sync should return them"
    assert "Feeds: 2" in text
    assert_private_text_absent(text)


@respx.mock
async def test_a_login_page_is_reported_by_status_class_and_kind_only() -> None:
    page = httpx.Response(
        404, text=f"<html>{PRIVATE[4]}</html>", headers={"content-type": "text/html"}
    )
    respx.get(FEED_1).mock(page)
    reports, text = await run(FEED_1)
    assert (reports[0].status_class, reports[0].content_kind) == ("4xx", "html")
    assert reports[0].size_bytes is None
    assert conclusion(reports).startswith("1 of 1 feeds could not be read")
    assert_private_text_absent(text)


@respx.mock
async def test_a_body_that_is_not_icalendar_is_a_problem_without_its_text() -> None:
    respx.get(FEED_1).mock(feed(f"{PRIVATE[4]} is not a calendar", "text/plain"))
    reports, text = await run(FEED_1)
    assert reports[0].problem == "the response is not an iCalendar feed"
    assert reports[0].content_kind == "text"
    assert_private_text_absent(text)


@respx.mock
async def test_an_unreachable_feed_and_an_unsafe_url_do_not_stop_the_others() -> None:
    respx.get(FEED_1).mock(side_effect=httpx.ConnectError("boom token-abc123"))
    respx.get(FEED_2).mock(feed(calendar(vevent("a", IN_WINDOW))))
    reports, text = await run(FEED_1, FEED_2, "http://10.0.0.1/secret-path-xyz")
    assert [report.problem for report in reports] == [
        "could not be reached",
        None,
        "the URL is not a public https address",
    ]
    assert "secret-path-xyz" not in text
    assert_private_text_absent(text)


async def test_no_feeds_says_to_connect_first() -> None:
    reports, text = await run()
    assert text.splitlines()[-1] == (
        "Conclusion: no feed URLs are stored: connect LearningSuite in Settings first"
    )
    assert reports == []


@pytest.mark.parametrize(
    ("header", "kind"),
    [
        ("text/calendar; charset=utf-8", "calendar"),
        ("TEXT/HTML", "html"),
        ("application/problem+json", "json"),
        ("application/octet-stream", "other"),
        (None, "missing"),
    ],
)
def test_content_type_is_reduced_to_a_kind(header: str | None, kind: str) -> None:
    assert content_kind(header) == kind


def test_status_is_reduced_to_a_class() -> None:
    assert [status_class(code) for code in (200, 302, 404, 503, 99)] == [
        "2xx",
        "3xx",
        "4xx",
        "5xx",
        "other",
    ]


class FixedClock:
    def now(self):  # noqa: ANN201
        return NOW


@respx.mock
async def test_a_sync_that_keeps_nothing_logs_counts_and_no_url_or_title(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.get(FEED_1).mock(feed(calendar(vevent("a", BEFORE), vevent("b", AFTER))))
    respx.get(FEED_2).mock(feed(calendar(vevent("c", BEFORE))))
    adapter = IcalFeedAdapter(DENVER, FixedClock())
    with caplog.at_level(logging.INFO, logger="command_center.adapters.ical_feed"):
        events = await adapter.fetch({"urls": f"{FEED_1}\n{FEED_2}"}, WINDOW)
    assert events == []
    assert [r.getMessage() for r in caplog.records] == [
        "Synced 0 items: 2 feeds, 3 events in the feeds, 0 inside the window"
    ]
    assert_private_text_absent(caplog.text)


@respx.mock
async def test_a_sync_that_keeps_something_logs_no_zero_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.get(FEED_1).mock(feed(calendar(vevent("a", IN_WINDOW))))
    adapter = IcalFeedAdapter(DENVER, FixedClock())
    with caplog.at_level(logging.INFO, logger="command_center.adapters.ical_feed"):
        events = await adapter.fetch({"urls": FEED_1}, WINDOW)
    assert len(events) == 1
    assert caplog.records == []


def test_the_zero_message_uses_singular_words() -> None:
    assert (
        zero_items_message(1, 1)
        == "Synced 0 items: 1 feed, 1 event in the feeds, 0 inside the window"
    )
