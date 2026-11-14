"""Restore applies only to today's done and dismissed entries (decisions 0334, 0404).

The day is the user's local day (America/Denver) by the injected clock. SQLite always, Postgres
with CC_TEST_POSTGRES_URL.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from command_center.services.items import RestoreTooOldError
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import DATABASES, open_engine

# 2026-11-07 is an ordinary day in Denver (UTC-7); 05:00 local = 12:00Z.
MORNING = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
JUST_BEFORE_MIDNIGHT = datetime(2026, 11, 8, 6, 59, tzinfo=UTC)  # 23:59 on 11-07 local
MIDNIGHT = datetime(2026, 11, 8, 7, 0, tzinfo=UTC)  # 00:00 on 11-08 local


@pytest.fixture(params=DATABASES)
def rig(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine(request.param, tmp_path):
        ledger_rig = open_ledger_rig(engine)
        ledger_rig.events.upsert([assignment("a", hours=1)])
        ledger_rig.clock.set(MORNING)
        yield ledger_rig


async def test_restoring_an_item_you_checked_off_today_works(rig: LedgerRig) -> None:
    await rig.items.check_off("a")
    rig.clock.set(JUST_BEFORE_MIDNIGHT)

    event = await rig.items.restore("a")

    assert event.status is None


async def test_restoring_an_item_you_dismissed_today_works(rig: LedgerRig) -> None:
    await rig.items.dismiss("a")
    rig.clock.set(JUST_BEFORE_MIDNIGHT)

    event = await rig.items.restore("a")

    assert event.dismissed_at is None


async def test_restoring_a_check_off_from_yesterday_is_refused_and_changes_nothing(
    rig: LedgerRig,
) -> None:
    await rig.items.check_off("a")
    rig.clock.advance(timedelta(days=1))

    with pytest.raises(RestoreTooOldError):
        await rig.items.restore("a")

    assert rig.ledger.marks(["a"])["a"].done_by == "user"


async def test_restoring_a_dismissal_from_yesterday_is_refused_and_changes_nothing(
    rig: LedgerRig,
) -> None:
    await rig.items.dismiss("a")
    rig.clock.advance(timedelta(days=1))

    with pytest.raises(RestoreTooOldError):
        await rig.items.restore("a")

    assert rig.ledger.marks(["a"])["a"].dismissed_at is not None


async def test_an_undo_after_local_midnight_for_an_action_just_before_it_is_refused(
    rig: LedgerRig,
) -> None:
    rig.clock.set(JUST_BEFORE_MIDNIGHT)
    await rig.items.check_off("a")
    rig.clock.set(MIDNIGHT)

    with pytest.raises(RestoreTooOldError):
        await rig.items.restore("a")


async def test_an_action_at_local_midnight_is_restorable_until_the_next_midnight(
    rig: LedgerRig,
) -> None:
    rig.clock.set(MIDNIGHT)
    await rig.items.dismiss("a")
    rig.clock.set(MIDNIGHT + timedelta(hours=24) - timedelta(minutes=1))

    event = await rig.items.restore("a")

    assert event.dismissed_at is None


async def test_the_local_day_not_the_utc_day_decides(rig: LedgerRig) -> None:
    # 23:30Z on 11-07 is 16:30 local on 11-07; 01:00Z on 11-08 is 18:00 local on 11-07: same day
    rig.clock.set(datetime(2026, 11, 7, 23, 30, tzinfo=UTC))
    await rig.items.check_off("a")
    rig.clock.set(datetime(2026, 11, 8, 1, 0, tzinfo=UTC))

    event = await rig.items.restore("a")

    assert event.status is None


async def test_on_a_25_hour_day_an_action_after_24_hours_is_still_today(rig: LedgerRig) -> None:
    # 2026-11-01 Denver falls back: 00:30 MDT = 06:30Z; the day ends at 07:00Z the next day.
    rig.clock.set(datetime(2026, 11, 1, 6, 30, tzinfo=UTC))
    await rig.items.check_off("a")
    rig.clock.set(datetime(2026, 11, 2, 6, 59, tzinfo=UTC))  # 23:59 MST, 24h29m later

    event = await rig.items.restore("a")

    assert event.status is None


async def test_on_a_25_hour_day_the_next_midnight_ends_it(rig: LedgerRig) -> None:
    rig.clock.set(datetime(2026, 11, 1, 6, 30, tzinfo=UTC))
    await rig.items.check_off("a")
    rig.clock.set(datetime(2026, 11, 2, 7, 0, tzinfo=UTC))  # 00:00 MST on 11-02

    with pytest.raises(RestoreTooOldError):
        await rig.items.restore("a")


async def test_on_a_23_hour_day_an_action_exactly_24_hours_ago_is_yesterday(
    rig: LedgerRig,
) -> None:
    # 2026-03-08 Denver springs forward. 03:30 MDT = 09:30Z; 24h later is 03:30 MDT on 03-09.
    rig.clock.set(datetime(2026, 3, 8, 9, 30, tzinfo=UTC))
    await rig.items.dismiss("a")
    rig.clock.set(datetime(2026, 3, 9, 9, 30, tzinfo=UTC))

    with pytest.raises(RestoreTooOldError):
        await rig.items.restore("a")


async def test_on_a_23_hour_day_an_action_22_hours_ago_is_still_today(rig: LedgerRig) -> None:
    rig.clock.set(datetime(2026, 3, 8, 7, 30, tzinfo=UTC))  # 00:30 MST
    await rig.items.dismiss("a")
    rig.clock.set(datetime(2026, 3, 9, 5, 30, tzinfo=UTC))  # 23:30 MDT on 03-08

    event = await rig.items.restore("a")

    assert event.dismissed_at is None


async def test_clearing_a_snooze_works_however_old_it_is(rig: LedgerRig) -> None:
    await rig.items.snooze("a", "next_week")
    rig.clock.advance(timedelta(days=3))

    event = await rig.items.restore("a")

    assert event.snoozed_until is None


async def test_restoring_twice_on_the_same_day_is_repeatable(rig: LedgerRig) -> None:
    await rig.items.dismiss("a")

    first = await rig.items.restore("a")
    second = await rig.items.restore("a")

    assert first == second


async def test_restoring_an_item_with_nothing_to_restore_is_allowed_on_any_day(
    rig: LedgerRig,
) -> None:
    rig.clock.advance(timedelta(days=40))

    event = await rig.items.restore("a")

    assert event.dismissed_at is None
