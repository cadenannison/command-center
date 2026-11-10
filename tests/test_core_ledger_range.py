"""Ledger history over a range of days: completed_by and local-day grouping across DST."""

from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from command_center.core.ledger import (
    HistoryDay,
    HistoryGroup,
    LedgerEntry,
    group_history_range,
)

DENVER = ZoneInfo("America/Denver")
EPOCH_2025 = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp())
EPOCH_2028 = int(datetime(2028, 1, 1, tzinfo=UTC).timestamp())
GROUPS: tuple[HistoryGroup, ...] = ("done_by_you", "done_by_source", "gone")


def entry(
    item_id: str,
    at: datetime,
    group: HistoryGroup = "done_by_you",
) -> LedgerEntry:
    return LedgerEntry(
        item_id=item_id,
        source="canvas",
        kind="assignment",
        title="Essay",
        at=at,
        group=group,
    )


def utc(month: int, day: int, hour: int, minute: int, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def days_of(result: list[HistoryDay]) -> list[date]:
    return [d.day for d in result]


def ids_in(day: HistoryDay) -> list[str]:
    return [e.item_id for e in (*day.done_by_you, *day.done_by_source, *day.gone)]


# completed_by


@pytest.mark.parametrize(
    ("group", "expected"),
    [("done_by_you", "user"), ("done_by_source", "source"), ("gone", None)],
)
def test_completed_by_follows_the_group(group: HistoryGroup, expected: str | None) -> None:
    assert entry("a", utc(3, 1, 12, 0), group).completed_by == expected


def test_completed_by_is_in_the_dump_and_the_schema() -> None:
    dumped = entry("a", utc(3, 1, 12, 0), "done_by_source").model_dump()
    assert dumped["completed_by"] == "source"
    schema = LedgerEntry.model_json_schema(mode="serialization")
    assert "completed_by" in schema["properties"]


def test_completed_by_is_not_an_input() -> None:
    raw = entry("a", utc(3, 1, 12, 0)).model_dump(exclude={"completed_by"})
    assert LedgerEntry.model_validate(raw).completed_by == "user"


# group_history_range


def test_empty_input_gives_no_days() -> None:
    assert group_history_range([], UTC) == []


def test_days_ascend_and_empty_days_are_omitted() -> None:
    entries = [
        entry("c", utc(3, 5, 12, 0)),
        entry("a", utc(3, 1, 12, 0)),
        entry("b", utc(3, 3, 12, 0), "gone"),
    ]
    result = group_history_range(entries, UTC)
    assert days_of(result) == [date(2026, 3, 1), date(2026, 3, 3), date(2026, 3, 5)]


def test_late_evening_and_just_after_midnight_land_on_different_days() -> None:
    entries = [
        entry("late", datetime(2026, 5, 10, 23, 30, tzinfo=DENVER)),
        entry("early", datetime(2026, 5, 11, 0, 30, tzinfo=DENVER)),
    ]
    result = group_history_range(entries, DENVER)
    assert days_of(result) == [date(2026, 5, 10), date(2026, 5, 11)]
    assert ids_in(result[0]) == ["late"]
    assert ids_in(result[1]) == ["early"]


def test_the_same_instant_is_a_different_day_in_a_different_zone() -> None:
    at = utc(5, 11, 3, 0)
    assert days_of(group_history_range([entry("a", at)], UTC)) == [date(2026, 5, 11)]
    assert days_of(group_history_range([entry("a", at)], DENVER)) == [date(2026, 5, 10)]


def test_each_day_is_built_like_group_history() -> None:
    entries = [
        entry("y", utc(3, 1, 12, 0), "done_by_you"),
        entry("s", utc(3, 1, 13, 0), "done_by_source"),
        entry("g", utc(3, 1, 14, 0), "gone"),
    ]
    (day,) = group_history_range(entries, UTC)
    assert [e.item_id for e in day.done_by_you] == ["y"]
    assert [e.item_id for e in day.done_by_source] == ["s"]
    assert [e.item_id for e in day.gone] == ["g"]


def test_spring_forward_day_is_bounded_by_local_midnights() -> None:
    # Denver 2026-03-08: midnight 07:00Z (-7), clock jumps at 09:00Z, next midnight 06:00Z (-6).
    entries = [
        entry("before", utc(3, 8, 6, 59)),
        entry("start", utc(3, 8, 7, 0)),
        entry("after-jump", utc(3, 8, 9, 0)),
        entry("last", utc(3, 9, 5, 59)),
        entry("next", utc(3, 9, 6, 0)),
    ]
    result = group_history_range(entries, DENVER)
    assert days_of(result) == [date(2026, 3, 7), date(2026, 3, 8), date(2026, 3, 9)]
    assert ids_in(result[0]) == ["before"]
    assert ids_in(result[1]) == ["start", "after-jump", "last"]
    assert ids_in(result[2]) == ["next"]


def test_fall_back_day_is_bounded_by_local_midnights() -> None:
    # Denver 2026-11-01: midnight 06:00Z (-6), 01:00 repeats at 08:00Z, next midnight 07:00Z (-7).
    entries = [
        entry("before", utc(11, 1, 5, 59)),
        entry("start", utc(11, 1, 6, 0)),
        entry("last", utc(11, 2, 6, 59)),
        entry("next", utc(11, 2, 7, 0)),
    ]
    result = group_history_range(entries, DENVER)
    assert days_of(result) == [date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2)]
    assert ids_in(result[0]) == ["before"]
    assert ids_in(result[1]) == ["start", "last"]
    assert ids_in(result[2]) == ["next"]


def test_repeated_hour_orders_by_instant_not_by_wall_clock_or_id() -> None:
    # 01:30 local happens twice on 2026-11-01: 07:30Z (MDT) then 08:30Z (MST).
    first = entry("z-first", utc(11, 1, 7, 30))
    second = entry("a-second", utc(11, 1, 8, 30))
    (day,) = group_history_range([second, first], DENVER)
    assert ids_in(day) == ["z-first", "a-second"]


def test_equal_instants_in_different_offsets_order_by_item_id() -> None:
    plus_two = timezone(timedelta(hours=2))
    at_utc = utc(3, 8, 12, 0)
    at_offset = at_utc.astimezone(plus_two)
    entries = [entry("b", at_offset), entry("a", at_utc)]
    (day,) = group_history_range(entries, DENVER)
    assert ids_in(day) == ["a", "b"]


@given(
    st.lists(
        st.builds(
            entry,
            item_id=st.text(alphabet="abcdef", min_size=1, max_size=3),
            at=st.integers(min_value=EPOCH_2025, max_value=EPOCH_2028).map(
                lambda seconds: datetime.fromtimestamp(seconds, UTC)
            ),
            group=st.sampled_from(GROUPS),
        ),
        max_size=30,
    ),
    st.sampled_from([DENVER, UTC, ZoneInfo("Asia/Kolkata"), ZoneInfo("Pacific/Auckland")]),
)
def test_every_entry_appears_once_under_its_own_local_day(
    entries: list[LedgerEntry], tz: ZoneInfo
) -> None:
    result = group_history_range(entries, tz)

    assert days_of(result) == sorted({e.at.astimezone(tz).date() for e in entries})
    seen: list[LedgerEntry] = []
    for day in result:
        for e in (*day.done_by_you, *day.done_by_source, *day.gone):
            assert e.at.astimezone(tz).date() == day.day
            seen.append(e)

    def key(e: LedgerEntry) -> tuple[datetime, str, str]:
        return (e.at, e.item_id, e.group)

    assert sorted(seen, key=key) == sorted(entries, key=key)
