"""needs_me: the inclusion rule, order, cap and invariants (decision 0385)."""

from datetime import datetime, timedelta
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from builders import NAIVE_INSTANTS, NOW, make_event
from command_center.core.needs_me import NEEDS_ME_LIMIT, NEEDS_ME_MIN_PRIORITY, needs_me
from command_center.core.schema import Event
from command_center.core.urgency import assess

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
FIXED = settings(derandomize=True, max_examples=200, deadline=None)


def task(id_: str, offset: timedelta | None, **fields: object) -> Event:
    due = None if offset is None else NOW + offset
    return make_event(id=id_, kind="assignment", due=due, **fields)


def ids(items: list[Event]) -> list[str]:
    return [row.id for row in needs_me(items, NOW)]


def test_the_threshold_is_five() -> None:
    assert NEEDS_ME_MIN_PRIORITY == 5
    assert NEEDS_ME_LIMIT == 20


def test_below_at_and_above_the_threshold() -> None:
    below = task("below", 5 * DAY)  # priority 3
    at = task("at", 36 * HOUR)  # priority 5
    above = task("above", 2 * HOUR)  # priority 7
    assert assess(below, NOW).priority == NEEDS_ME_MIN_PRIORITY - 2
    assert assess(at, NOW).priority == NEEDS_ME_MIN_PRIORITY
    assert ids([below, at, above]) == ["above", "at"]


def test_overdue_is_included_and_done_is_not() -> None:
    late = task("late", -HOUR)
    done = task("done", -HOUR, status="done")
    assert ids([late, done]) == ["late"]


def test_an_overdue_item_below_the_threshold_is_included() -> None:
    # An overdue reply scores 5 on its own, so this pins the overdue path, not the threshold.
    mail = make_event(id="mail", kind="email", status="overdue", start=NOW - HOUR)
    assert ids([mail]) == ["mail"]


def test_undated_items_never_qualify() -> None:
    assert ids([task("undated", None), make_event(id="m", kind="email", status="owed")]) == []


def test_events_in_progress_or_within_a_day_qualify() -> None:
    now_event = make_event(id="now", start=NOW - HOUR, end=NOW + HOUR)
    soon = make_event(id="soon", start=NOW + 23 * HOUR)
    later = make_event(id="later", start=NOW + 25 * HOUR)
    over = make_event(id="over", start=NOW - 2 * HOUR, end=NOW - HOUR)
    no_end = make_event(id="no-end", start=NOW - HOUR)
    assert ids([now_event, soon, later, over, no_end]) == ["now", "soon"]


def test_weather_is_never_included() -> None:
    assert ids([make_event(id="w", kind="weather", start=NOW)]) == []


def test_order_is_priority_then_time_then_id() -> None:
    items = [
        task("b", 3 * HOUR),
        task("a", 3 * HOUR),
        task("sooner", 2 * HOUR),
        task("late", -HOUR),
    ]
    assert ids(items) == ["late", "sooner", "a", "b"]


def test_the_cap_keeps_the_most_urgent() -> None:
    items = [task(f"t{i:02}", -HOUR * (i + 1)) for i in range(30)]
    rows = needs_me(items, NOW)
    assert len(rows) == NEEDS_ME_LIMIT
    assert [r.id for r in rows] == [f"t{29 - i:02}" for i in range(NEEDS_ME_LIMIT)]
    assert len(needs_me(items, NOW, limit=3)) == 3
    assert needs_me(items, NOW, limit=0) == []


def test_an_id_never_appears_twice() -> None:
    items = [task("dup", -HOUR), task("dup", 2 * HOUR), task("other", -HOUR)]
    assert sorted(ids(items)) == ["dup", "other"]


def test_the_same_input_gives_the_same_list_in_any_order() -> None:
    items = [task(f"t{i}", (i - 3) * HOUR) for i in range(8)]
    assert needs_me(items, NOW) == needs_me(items, NOW)
    assert needs_me(items, NOW) == needs_me(list(reversed(items)), NOW)


def test_a_row_carries_due_else_start_and_the_reasons() -> None:
    mail = make_event(id="m", kind="email", status="overdue", start=NOW - HOUR, link="https://x")
    (row,) = needs_me([mail], NOW)
    assert (row.kind, row.at, row.link) == ("email", NOW - HOUR, "https://x")
    assert row.reasons[0].code == "reply_overdue"


def test_a_negative_limit_is_refused() -> None:
    with pytest.raises(ValueError, match="limit"):
        needs_me([], NOW, limit=-1)


@pytest.mark.parametrize("naive", NAIVE_INSTANTS)
def test_a_naive_now_is_refused(naive: datetime) -> None:
    with pytest.raises(ValueError, match="timezone"):
        needs_me([task("x", HOUR)], naive)


kinds = st.sampled_from(["assignment", "task", "email", "event", "weather"])
offsets = st.one_of(st.none(), st.integers(-200, 200).map(lambda h: h * HOUR))


@st.composite
def events(draw: st.DrawFn) -> Event:
    kind = draw(kinds)
    start = draw(offsets)
    due = draw(offsets)
    status = draw(st.sampled_from([None, "done", "owed", "overdue"]))
    return make_event(
        id=draw(st.sampled_from([f"i{n}" for n in range(40)])),
        kind=kind,
        start=None if start is None else NOW + start,
        end=None if start is None else NOW + start + HOUR,
        due=None if due is None else NOW + due,
        status=status,
    )


@FIXED
@given(st.lists(events(), max_size=60))
def test_property_cap_order_and_rule(items: list[Event]) -> None:
    rows = needs_me(items, NOW)
    assert len(rows) <= NEEDS_ME_LIMIT
    assert len({r.id for r in rows}) == len(rows)
    keys = [(-r.priority, r.at is None, r.at, r.id) for r in rows]
    assert [k[:2] for k in keys] == sorted(k[:2] for k in keys)
    for earlier, later in pairwise(rows):
        if earlier.priority == later.priority and earlier.at and later.at:
            assert earlier.at <= later.at
    for row in rows:
        assert row.at is not None
        codes = {reason.code for reason in row.reasons}
        assert row.kind != "weather"
        assert any(e.id == row.id and e.status != "done" for e in items)
        if row.kind == "event":
            assert codes & {"event_now", "event_today"}
        else:
            assert row.priority >= NEEDS_ME_MIN_PRIORITY or codes & {"overdue", "reply_overdue"}
