"""AppleCalendarAdapter: a fake CalDAV session stands in for iCloud; no network."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from caldav.lib.error import AuthorizationError, DAVError

from builders import NOW
from command_center.adapters import caldav_apple
from command_center.adapters.caldav_apple import AppleCalendarAdapter, CalendarHandle
from command_center.adapters.ical_events import EXPANSION_PAD
from command_center.core.errors import AuthExpired, FatalError, TransientError
from command_center.core.windows import TimeWindow
from ics_support import DENVER, WINDOW, load, utc

CREDS = {"username": "fake-user@icloud.example", "app_password": "fake-abcd-efgh-ijkl-mnop"}


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeCalendar:
    def __init__(self, key: str, label: str, *items: str, error: Exception | None = None) -> None:
        self.key, self.label, self._items, self._error = key, label, items, error
        self.asked: list[tuple[datetime, datetime]] = []

    def event_data(self, start: datetime, end: datetime) -> Sequence[str]:
        self.asked.append((start, end))
        if self._error is not None:
            raise self._error
        return self._items


class FakeSession:
    def __init__(self, *calendars: CalendarHandle, login_error: Exception | None = None) -> None:
        self._calendars, self._login_error = calendars, login_error
        self.closed = False

    def calendars(self) -> Sequence[CalendarHandle]:
        if self._login_error is not None:
            raise self._login_error
        return self._calendars

    def close(self) -> None:
        self.closed = True


def adapter_for(session: FakeSession) -> AppleCalendarAdapter:
    return AppleCalendarAdapter(DENVER, FakeClock(), lambda _user, _password: session)


async def test_fetch_returns_events_from_every_calendar() -> None:
    session = FakeSession(
        FakeCalendar("/home", "Home", load("allday.ics")),
        FakeCalendar("/work", "Work", load("recurring.ics")),
    )
    events = await adapter_for(session).fetch(CREDS, WINDOW)
    assert len(events) == 3 + 4
    assert {e.kind for e in events} == {"event"}
    assert {e.source for e in events} == {"apple_calendar"}
    assert {e.raw["calendar"] for e in events} == {"Home", "Work"}


async def test_fetch_asks_each_calendar_for_the_window_padded_on_both_sides() -> None:
    home = FakeCalendar("/home", "Home", load("allday.ics"))
    await adapter_for(FakeSession(home)).fetch(CREDS, WINDOW)
    assert home.asked == [(WINDOW.start - EXPANSION_PAD, WINDOW.end + EXPANSION_PAD)]


async def test_fetch_expands_a_master_the_server_left_unexpanded() -> None:
    events = await adapter_for(FakeSession(FakeCalendar("/w", "W", load("recurring.ics")))).fetch(
        CREDS, WINDOW
    )
    assert len(events) == 4


async def test_fetch_accepts_already_expanded_instances() -> None:
    instance = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\nUID:u\nDTSTAMP:20261001T000000Z\n"
        "RECURRENCE-ID;TZID=America/Denver:20261104T090000\n"
        "DTSTART;TZID=America/Denver:20261104T090000\nDTEND;TZID=America/Denver:20261104T093000\n"
        "SUMMARY:One instance\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    events = await adapter_for(FakeSession(FakeCalendar("/w", "W", instance))).fetch(CREDS, WINDOW)
    assert [e.title for e in events] == ["One instance"]


async def test_floating_and_all_day_items_use_the_constructor_zone() -> None:
    events = await adapter_for(
        FakeSession(FakeCalendar("/h", "H", load("floating.ics"), load("allday.ics")))
    ).fetch(CREDS, WINDOW)
    morning = next(e for e in events if e.title == "Floating morning")
    holiday = next(e for e in events if e.title == "Veterans Day break")
    assert morning.start is not None
    assert morning.start.utcoffset() == datetime(2026, 11, 10, tzinfo=DENVER).utcoffset()
    assert holiday.start == datetime(2026, 11, 10, tzinfo=DENVER)


async def test_the_same_event_in_two_calendars_stays_two_events() -> None:
    session = FakeSession(
        FakeCalendar("/a", "A", load("floating.ics")), FakeCalendar("/b", "B", load("floating.ics"))
    )
    events = await adapter_for(session).fetch(CREDS, WINDOW)
    assert len(events) == len({e.id for e in events}) == 4


async def test_one_failing_calendar_raises_and_returns_nothing() -> None:
    session = FakeSession(
        FakeCalendar("/a", "A", load("floating.ics")),
        FakeCalendar("/b", "B", error=DAVError("boom")),
    )
    with pytest.raises(TransientError):
        await adapter_for(session).fetch(CREDS, WINDOW)
    assert session.closed


async def test_an_unparseable_item_fails_the_whole_fetch() -> None:
    session = FakeSession(FakeCalendar("/a", "A", load("floating.ics"), "<html>nope</html>"))
    with pytest.raises(FatalError, match="could not be parsed"):
        await adapter_for(session).fetch(CREDS, WINDOW)


async def test_rejected_login_is_auth_expired_and_quotes_no_credential() -> None:
    session = FakeSession(login_error=AuthorizationError(f"401 for {CREDS['username']}"))
    with pytest.raises(AuthExpired) as caught:
        await adapter_for(session).fetch(CREDS, WINDOW)
    assert CREDS["username"] not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert session.closed


@pytest.mark.parametrize("failure", [OSError("connection reset"), DAVError("503")])
async def test_network_and_server_errors_are_transient(failure: Exception) -> None:
    session = FakeSession(login_error=failure)
    with pytest.raises(TransientError) as caught:
        await adapter_for(session).fetch(CREDS, WINDOW)
    assert "connection reset" not in str(caught.value)


@pytest.mark.parametrize("creds", [{}, {"username": "fake-u"}, {"app_password": "fake-p"}])
async def test_fetch_without_both_credentials_needs_a_reconnect(creds: dict[str, str]) -> None:
    with pytest.raises(AuthExpired):
        await adapter_for(FakeSession()).fetch(creds, WINDOW)


async def test_validate_logs_in_and_lists_calendars() -> None:
    session = FakeSession(FakeCalendar("/a", "A"), FakeCalendar("/b", "B"))
    result = await adapter_for(session).validate(CREDS)
    assert (result.ok, result.message) == (True, "Connected to iCloud (2 calendars)")
    assert session.closed


async def test_validate_with_rejected_credentials_raises_auth_expired() -> None:
    session = FakeSession(login_error=AuthorizationError("401"))
    with pytest.raises(AuthExpired):
        await adapter_for(session).validate(CREDS)
    assert session.closed


async def test_validate_with_a_server_error_raises_transient() -> None:
    with pytest.raises(TransientError):
        await adapter_for(FakeSession(login_error=OSError("down"))).validate(CREDS)


async def test_validate_with_missing_credentials_is_not_ok_without_connecting() -> None:
    def explode(_user: str, _password: str) -> FakeSession:
        msg = "must not connect"
        raise AssertionError(msg)

    result = await AppleCalendarAdapter(DENVER, FakeClock(), explode).validate(
        {"username": "fake-u"}
    )
    assert result.ok is False


def test_the_source_name_is_apple_calendar() -> None:
    assert adapter_for(FakeSession()).name == "apple_calendar"


class FakeObject:
    def __init__(self, data: str) -> None:
        self.data = data


class FakeDavCalendar:
    def __init__(self) -> None:
        self.url = "https://caldav.icloud.com/123/calendars/home/"
        self.name = "Home"
        self.search_args: dict[str, Any] = {}

    def search(self, **kwargs: Any) -> list[FakeObject]:  # noqa: ANN401
        self.search_args = kwargs
        return [FakeObject(load("floating.ics"))]


class FakePrincipal:
    def __init__(self, calendar: FakeDavCalendar) -> None:
        self._calendar = calendar

    def get_calendars(self) -> list[FakeDavCalendar]:
        return [self._calendar]


class FakeDavClient:
    instances: list["FakeDavClient"] = []  # noqa: RUF012

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        self.kwargs, self.closed = kwargs, False
        self.calendar = FakeDavCalendar()
        FakeDavClient.instances.append(self)

    def principal(self) -> FakePrincipal:
        return FakePrincipal(self.calendar)

    def close(self) -> None:
        self.closed = True


async def test_the_real_session_logs_in_to_icloud_and_searches_with_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeDavClient.instances.clear()
    monkeypatch.setattr(caldav_apple, "DAVClient", FakeDavClient)
    events = await AppleCalendarAdapter(DENVER, FakeClock()).fetch(CREDS, WINDOW)
    (client,) = FakeDavClient.instances
    assert client.kwargs == {
        "url": "https://caldav.icloud.com/",
        "username": CREDS["username"],
        "password": CREDS["app_password"],
        "timeout": 10,
    }
    assert client.calendar.search_args == {
        "start": WINDOW.start - EXPANSION_PAD,
        "end": WINDOW.end + EXPANSION_PAD,
        "event": True,
        "expand": True,
    }
    assert client.closed
    assert {e.title for e in events} == {"Floating morning", "Floating late"}
    assert {e.raw["calendar"] for e in events} == {"Home"}


class UtcMatchingCalendar:
    """Like caldav, which matches floating and all-day items in the zone of the request."""

    key = "/utc"
    label = "Utc"

    def __init__(self, *items: tuple[datetime, str]) -> None:
        self._items = items

    def event_data(self, start: datetime, end: datetime) -> Sequence[str]:
        return [text for naive, text in self._items if start <= naive.replace(tzinfo=UTC) < end]


def floating(uid: str, start: str) -> str:
    return (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\n"
        f"UID:{uid}\nDTSTAMP:20261001T000000Z\nDTSTART:{start}\nDTEND:{start[:9]}235900\n"
        f"SUMMARY:{uid}\nEND:VEVENT\nEND:VCALENDAR\n"
    )


async def test_edge_items_survive_a_server_that_matches_floating_times_in_utc() -> None:
    utc_window = TimeWindow(start=utc(2026, 11, 10), end=utc(2026, 11, 17))
    # 20:00 Denver on Nov 9 is 03:00Z on Nov 10: inside the window, but 20:00 read as UTC is not.
    before_edge = (
        datetime(2026, 11, 9, 20, tzinfo=UTC),
        floating("before-edge", "20261109T200000"),
    )
    # 20:00 Denver on Nov 16 is 03:00Z on Nov 17: outside, so it must be filtered out here.
    after_edge = (datetime(2026, 11, 16, 20, tzinfo=UTC), floating("after-edge", "20261116T200000"))
    session = FakeSession(UtcMatchingCalendar(before_edge, after_edge))
    events = await adapter_for(session).fetch(CREDS, utc_window)
    assert [e.title for e in events] == ["before-edge"]


async def test_an_unexpected_vendor_error_becomes_transient_and_leaks_nothing() -> None:
    class VendorBugError(Exception):
        pass

    session = FakeSession(
        FakeCalendar("/a", "A", error=VendorBugError(f"{CREDS['username']} /123/"))
    )
    with pytest.raises(TransientError) as caught:
        await adapter_for(session).fetch(CREDS, WINDOW)
    assert CREDS["username"] not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert session.closed


async def test_validate_turns_an_unexpected_vendor_error_into_transient() -> None:
    with pytest.raises(TransientError):
        await adapter_for(FakeSession(login_error=KeyError("boom"))).validate(CREDS)
