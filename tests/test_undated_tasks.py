"""Undated open tasks in GET /v1/tasks (decision 0372): urgency, the store query, the cap, order."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from builders import NOW, make_event
from command_center.core.schema import Event
from command_center.core.urgency import assess
from command_center.services.agenda import UNDATED_TASK_CAP, AgendaService
from command_center.storage.sqlite import create_event_store
from fakes import FakeClock, InMemoryEventStore
from ledger_support import LedgerRig, open_ledger_rig
from sink_support import open_engine

DENVER = ZoneInfo("America/Denver")
DAY = timedelta(days=1)
FIXED = settings(derandomize=True, max_examples=200, deadline=None)


def service_over(*events: Event) -> AgendaService:
    store = InMemoryEventStore()
    store.upsert(list(events))
    return AgendaService(store, FakeClock(NOW), DENVER)


def test_a_plain_undated_manual_task_scores_one_with_a_no_due_date_reason() -> None:
    result = assess(make_event(kind="task", source="local"), NOW)

    assert result.priority == 1
    assert result.score == 1
    assert [(r.code, r.points, r.text) for r in result.reasons] == [
        ("no_due", 0, "No due date"),
        ("manual", 1, "You added this task yourself"),
    ]


def test_an_undated_task_from_another_source_has_only_the_no_due_date_reason() -> None:
    result = assess(make_event(kind="assignment", source="canvas"), NOW)

    assert [(r.code, r.points) for r in result.reasons] == [("no_due", 0)]
    assert result.priority == 1


@FIXED
@given(
    st.sampled_from(["assignment", "task"]),
    st.sampled_from(["local", "canvas"]),
    st.timedeltas(min_value=-400 * DAY, max_value=400 * DAY),
)
def test_a_dated_item_never_scores_lower_than_an_undated_one_from_the_same_source(
    kind: str, source: str, offset: timedelta
) -> None:
    dated = assess(make_event(kind=kind, source=source, due=NOW + offset), NOW)
    undated = assess(make_event(kind=kind, source=source), NOW)

    assert dated.score >= undated.score


async def test_an_open_undated_manual_task_appears_in_the_tasks_list() -> None:
    task = make_event(id="manual", kind="task", source="local", title="Call the bank")

    [item] = await service_over(task).tasks()

    assert (item.id, item.due, item.done, item.priority) == ("manual", None, False, 1)
    assert [r.text for r in item.reasons] == ["No due date", "You added this task yourself"]


async def test_an_undated_done_task_is_left_out() -> None:
    done = make_event(id="done", kind="task", source="local", status="done")

    assert await service_over(done).tasks() == []


async def test_undated_calendar_events_and_email_stay_out() -> None:
    items = [
        make_event(id="weather", kind="weather"),
        make_event(id="mail", kind="email", source="gmail", status="owed"),
        make_event(id="meeting", kind="event"),
    ]

    assert await service_over(*items).tasks() == []


async def test_the_undated_list_is_capped_with_the_newest_created_first() -> None:
    events = [
        make_event(
            id=f"t{n:03}", kind="task", source="local", fetched_at=NOW + timedelta(minutes=n)
        )
        for n in range(UNDATED_TASK_CAP + 5)
    ]

    items = await service_over(*events).tasks()

    assert len(items) == UNDATED_TASK_CAP
    assert {i.id for i in items} == {e.id for e in events[5:]}


async def test_equal_created_times_are_cut_by_id() -> None:
    events = [make_event(id=f"t{n:03}", kind="task") for n in range(UNDATED_TASK_CAP + 1)]

    items = await service_over(*events).tasks()

    assert "t200" not in {i.id for i in items}
    assert len(items) == UNDATED_TASK_CAP


async def test_order_is_priority_then_due_then_undated_last_then_id() -> None:
    items = [
        make_event(id="z-undated", kind="task", source="local"),
        make_event(id="a-undated", kind="task", source="local"),
        make_event(id="soon", kind="task", source="local", due=NOW + timedelta(hours=3)),
        make_event(id="far", kind="task", source="local", due=NOW + 30 * DAY),
        make_event(id="b-plain", kind="assignment", source="canvas"),
    ]

    ranked = await service_over(*items).tasks()

    assert [t.id for t in ranked] == ["soon", "far", "a-undated", "b-plain", "z-undated"]


@pytest.fixture
def ledger_rig(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


async def test_a_checked_off_undated_task_is_dropped_but_a_dated_one_stays_done(
    ledger_rig: LedgerRig,
) -> None:
    ledger_rig.events.upsert(
        [
            make_event(id="undated", kind="task", source="canvas"),
            make_event(id="dated", kind="task", source="canvas", due=NOW + DAY),
        ]
    )
    ledger_rig.ledger.check_off("undated", NOW)
    ledger_rig.ledger.check_off("dated", NOW)

    items = await ledger_rig.agenda.tasks()

    assert [(i.id, i.done) for i in items] == [("dated", True)]


def test_sqlite_undated_open_filters_orders_and_limits() -> None:
    store = create_event_store("sqlite://")
    store.upsert(
        [
            make_event(id="old", kind="task", fetched_at=NOW),
            make_event(id="new", kind="task", fetched_at=NOW + timedelta(hours=1)),
            make_event(id="done", kind="task", status="done", fetched_at=NOW),
            make_event(id="dated", kind="task", due=NOW + DAY),
            make_event(id="mail", kind="email"),
        ]
    )
    store.upsert([make_event(id="other", kind="task", user_id="someone")], user_id="someone")

    assert [e.id for e in store.undated_open(("task", "assignment"), 10)] == ["new", "old"]
    assert [e.id for e in store.undated_open(("task", "assignment"), 1)] == ["new"]
    assert store.undated_open(("task", "assignment"), 0) == []
    store.close()
