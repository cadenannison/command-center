"""History by day in the settings timezone, across both DST changes (decision 0123).

America/Denver: clocks go forward on 2026-03-08 (a 23-hour day) and back on 2026-11-01 (a 25-hour
day). Check-offs are stamped at instants either side of each local midnight, through the real
SQL ledger (SQLite always, Postgres with CC_TEST_POSTGRES_URL).
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from builders import NOW
from command_center.core.ledger import HistoryDay
from command_center.core.windows import TimeWindow
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import DATABASES, open_engine

EVERYTHING = TimeWindow(start=NOW - timedelta(days=30), end=NOW + timedelta(days=30))


@pytest.fixture(params=DATABASES)
def rig(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine(request.param, tmp_path):
        yield open_ledger_rig(engine)


def utc(month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def check_off_at(rig: LedgerRig, item_id: str, at: datetime) -> None:
    rig.events.upsert([assignment(item_id)])
    assert rig.ledger.check_off(item_id, at) is True


def ids_by_day(days: list[HistoryDay]) -> dict[date, list[str]]:
    return {d.day: [e.item_id for e in d.done_by_you] for d in days}


async def test_the_25_hour_fall_back_day_holds_its_first_and_last_minute(rig: LedgerRig) -> None:
    # Local midnights: Nov 1 00:00 MDT is 06:00Z, Nov 2 00:00 MST is 07:00Z.
    check_off_at(rig, "before", utc(11, 1, 5, 59))  # Oct 31 23:59 MDT
    check_off_at(rig, "first", utc(11, 1, 6, 0))  # Nov 1 00:00 MDT
    check_off_at(rig, "repeated-hour", utc(11, 1, 7, 30))  # 01:30 MDT, the first 01:30
    check_off_at(rig, "last", utc(11, 2, 6, 59))  # Nov 1 23:59 MST
    check_off_at(rig, "next", utc(11, 2, 7, 0))  # Nov 2 00:00 MST

    just_the_long_day = await rig.items.history(date(2026, 11, 1), date(2026, 11, 1))
    assert ids_by_day(just_the_long_day) == {date(2026, 11, 1): ["first", "repeated-hour", "last"]}

    around = await rig.items.history(date(2026, 10, 31), date(2026, 11, 2))
    assert ids_by_day(around) == {
        date(2026, 10, 31): ["before"],
        date(2026, 11, 1): ["first", "repeated-hour", "last"],
        date(2026, 11, 2): ["next"],
    }


async def test_the_23_hour_spring_forward_day_holds_its_first_and_last_minute(
    rig: LedgerRig,
) -> None:
    # Local midnights: Mar 8 00:00 MST is 07:00Z, Mar 9 00:00 MDT is 06:00Z.
    check_off_at(rig, "before", utc(3, 8, 6, 59))  # Mar 7 23:59 MST
    check_off_at(rig, "first", utc(3, 8, 7, 0))  # Mar 8 00:00 MST
    check_off_at(rig, "last", utc(3, 9, 5, 59))  # Mar 8 23:59 MDT
    check_off_at(rig, "next", utc(3, 9, 6, 0))  # Mar 9 00:00 MDT

    long_range = await rig.items.history(date(2026, 3, 7), date(2026, 3, 9))
    assert ids_by_day(long_range) == {
        date(2026, 3, 7): ["before"],
        date(2026, 3, 8): ["first", "last"],
        date(2026, 3, 9): ["next"],
    }
    one_day = await rig.items.history(date(2026, 3, 8), date(2026, 3, 8))
    assert ids_by_day(one_day) == {date(2026, 3, 8): ["first", "last"]}


async def test_days_with_nothing_to_show_are_left_out_and_days_are_oldest_first(
    rig: LedgerRig,
) -> None:
    check_off_at(rig, "late", utc(11, 5, 18, 0))
    check_off_at(rig, "early", utc(11, 2, 18, 0))

    days = await rig.items.history(date(2026, 11, 1), date(2026, 11, 7))

    assert [d.day for d in days] == [date(2026, 11, 2), date(2026, 11, 5)]


async def test_an_empty_range_is_an_empty_list(rig: LedgerRig) -> None:
    assert await rig.items.history(date(2026, 11, 1), date(2026, 11, 7)) == []


async def test_a_day_splits_what_you_did_from_what_the_source_did_and_what_vanished(
    rig: LedgerRig,
) -> None:
    rig.events.replace("canvas", EVERYTHING, [assignment("kept"), assignment("lost")])
    rig.events.replace(
        "canvas",
        EVERYTHING,
        [assignment("kept", status="done")],
    )  # lost vanished and kept was completed at the source, both at the store's clock
    await rig.items.set_note("kept", "turned in early")
    await rig.items.check_off("kept")  # you also checked it off: both completions are entries

    (day,) = await rig.items.history(NOW.date(), NOW.date())

    assert [e.item_id for e in day.done_by_source] == ["kept"]
    assert [e.item_id for e in day.gone] == ["lost"]
    assert [e.item_id for e in day.done_by_you] == ["kept"]
    assert day.done_by_source[0].note == "turned in early"
    assert day.done_by_source[0].completed_by == "source"
    assert day.gone[0].completed_by is None
