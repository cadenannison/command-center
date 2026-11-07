"""AgendaService: windows in the user's timezone, scoring at read time, ordering, attention."""

from collections.abc import Collection
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from builders import NOW, make_event
from command_center.core.schema import Event, EventKind
from command_center.core.scoring import urgency
from command_center.core.windows import TimeWindow
from command_center.services.agenda import AgendaService
from fakes import FakeClock, InMemoryEventStore

DENVER = ZoneInfo("America/Denver")  # UTC-7 in November, so NOW is 05:00 local on 2026-11-07
TODAY = date(2026, 11, 7)


def make_service(*events: Event, clock: FakeClock | None = None) -> AgendaService:
    store = InMemoryEventStore()
    store.upsert(list(events))
    return AgendaService(store, clock or FakeClock(NOW), DENVER)


def ids(events: list[Event]) -> list[str]:
    return [e.id for e in events]


async def test_day_returns_events_ordered_by_start_then_due() -> None:
    late = make_event(id="late", start=NOW + timedelta(hours=5))
    due = make_event(id="due", kind="assignment", due=NOW + timedelta(hours=3))
    early = make_event(id="early", start=NOW + timedelta(hours=1))

    result = await make_service(late, due, early).day(TODAY)

    assert ids(result) == ["early", "due", "late"]


async def test_day_uses_the_configured_timezone_not_utc() -> None:
    evening = make_event(id="evening", start=datetime(2026, 11, 8, 3, 0, tzinfo=UTC))  # 20:00 MST
    service = make_service(evening)

    assert ids(await service.day(TODAY)) == ["evening"]
    assert await service.day(date(2026, 11, 8)) == []


async def test_week_runs_monday_to_monday() -> None:
    monday = make_event(id="mon", start=datetime(2026, 11, 2, 15, 0, tzinfo=UTC))
    sunday = make_event(id="sun", start=datetime(2026, 11, 8, 15, 0, tzinfo=UTC))
    next_monday = make_event(id="next", start=datetime(2026, 11, 9, 15, 0, tzinfo=UTC))
    before = make_event(id="before", start=datetime(2026, 11, 1, 15, 0, tzinfo=UTC))

    result = await make_service(monday, sunday, next_monday, before).week(TODAY)

    assert ids(result) == ["mon", "sun"]


async def test_month_covers_the_calendar_month_of_the_date() -> None:
    first = make_event(id="first", start=datetime(2026, 11, 1, 15, 0, tzinfo=UTC))
    last = make_event(id="last", start=datetime(2026, 11, 30, 15, 0, tzinfo=UTC))
    december = make_event(id="dec", start=datetime(2026, 12, 1, 15, 0, tzinfo=UTC))

    result = await make_service(first, last, december).month(TODAY)

    assert ids(result) == ["first", "last"]


async def test_between_returns_events_in_an_arbitrary_window() -> None:
    inside = make_event(id="in", start=NOW + timedelta(days=3))
    outside = make_event(id="out", start=NOW + timedelta(days=30))
    window = TimeWindow(start=NOW, end=NOW + timedelta(days=7))

    assert ids(await make_service(inside, outside).between(window)) == ["in"]


async def test_stored_urgency_is_ignored_and_rescored_against_the_clock() -> None:
    clock = FakeClock(NOW)
    due = NOW + timedelta(hours=48)
    service = make_service(make_event(id="a", kind="assignment", due=due, urgency=5), clock=clock)

    (before,) = await service.between(TimeWindow(start=NOW, end=NOW + timedelta(days=5)))
    clock.advance(timedelta(hours=30))
    (after,) = await service.between(TimeWindow(start=NOW, end=NOW + timedelta(days=5)))

    assert (before.urgency, after.urgency) == (70, 90)


async def test_scoring_reads_today_in_the_configured_timezone() -> None:
    # 22:00 MST on Nov 7 is Nov 8 in UTC: "later today" (40) only when now is read in Denver.
    event = make_event(id="e", start=datetime(2026, 11, 8, 5, 0, tzinfo=UTC))

    (result,) = await make_service(event).day(TODAY)

    assert result.urgency == 40
    assert urgency(event, NOW) == 10


async def test_attention_includes_urgent_assignments_and_owed_or_overdue_email() -> None:
    urgent = make_event(id="urgent", kind="assignment", due=NOW + timedelta(hours=10))
    owed = make_event(id="owed", kind="email", status="owed", due=NOW + timedelta(days=1))
    overdue = make_event(id="overdue", kind="email", status="overdue", due=NOW - timedelta(days=1))
    fyi = make_event(id="fyi", kind="email", due=NOW + timedelta(days=1))
    meeting = make_event(id="meeting", start=NOW + timedelta(hours=1))  # urgency 60
    later = make_event(id="later", kind="assignment", due=NOW + timedelta(days=5))  # urgency 40

    result = await make_service(urgent, owed, overdue, fyi, meeting, later).attention()

    assert set(ids(result)) == {"urgent", "owed", "overdue"}


async def test_attention_orders_most_urgent_first_then_by_time() -> None:
    soon = make_event(id="soon", kind="assignment", due=NOW + timedelta(hours=10))
    sooner = make_event(id="sooner", kind="assignment", due=NOW + timedelta(hours=5))
    overdue = make_event(id="overdue", kind="assignment", due=NOW - timedelta(hours=1))
    owed = make_event(id="owed", kind="email", status="owed", due=NOW + timedelta(days=2))

    result = await make_service(soon, sooner, overdue, owed).attention()

    assert ids(result) == ["overdue", "sooner", "soon", "owed"]
    assert [e.urgency for e in result] == [100, 90, 90, 50]


async def test_attention_ignores_stored_urgency_and_finished_work() -> None:
    done = make_event(id="done", kind="assignment", status="done", due=NOW + timedelta(hours=2))
    stale = make_event(id="stale", kind="assignment", due=NOW + timedelta(days=5), urgency=99)

    assert await make_service(done, stale).attention() == []


async def test_attention_looks_back_14_days_and_no_further() -> None:
    recent = make_event(id="recent", kind="assignment", due=NOW - timedelta(days=5))
    ancient = make_event(id="ancient", kind="assignment", due=NOW - timedelta(days=30))

    assert ids(await make_service(recent, ancient).attention()) == ["recent"]


async def test_events_the_store_returns_without_a_date_sort_last() -> None:
    class UndatedStore(InMemoryEventStore):
        def query(
            self,
            window: TimeWindow,  # noqa: ARG002
            kinds: Collection[EventKind] | None = None,  # noqa: ARG002
            *,
            user_id: str = "local",  # noqa: ARG002
        ) -> list[Event]:
            return [make_event(id="undated", kind="weather"), make_event(id="dated", start=NOW)]

    service = AgendaService(UndatedStore(), FakeClock(NOW), DENVER)

    assert ids(await service.between(TimeWindow(start=NOW, end=NOW + timedelta(days=1)))) == [
        "dated",
        "undated",
    ]
