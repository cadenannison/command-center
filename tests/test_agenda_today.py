"""AgendaService.today and .tz: the web views need the user's calendar day and timezone."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from builders import NOW
from command_center.services.agenda import AgendaService
from fakes import FakeClock, InMemoryEventStore

DENVER = ZoneInfo("America/Denver")  # UTC-7 in November


def make_service(clock: FakeClock) -> AgendaService:
    return AgendaService(InMemoryEventStore(), clock, DENVER)


def test_today_is_the_calendar_day_in_the_configured_timezone() -> None:
    assert make_service(FakeClock(NOW)).today() == date(2026, 11, 7)


def test_today_is_still_yesterday_after_midnight_utc_but_before_midnight_local() -> None:
    clock = FakeClock(datetime(2026, 11, 8, 3, 0, tzinfo=UTC))  # 20:00 on Nov 7 in Denver

    assert make_service(clock).today() == date(2026, 11, 7)


def test_today_follows_the_clock() -> None:
    clock = FakeClock(datetime(2026, 11, 8, 6, 59, tzinfo=UTC))  # 23:59 on Nov 7 in Denver
    service = make_service(clock)
    before = service.today()

    clock.set(datetime(2026, 11, 8, 7, 0, tzinfo=UTC))  # midnight Nov 8 in Denver

    assert (before, service.today()) == (date(2026, 11, 7), date(2026, 11, 8))


def test_tz_is_the_configured_timezone() -> None:
    assert make_service(FakeClock(NOW)).tz is DENVER
