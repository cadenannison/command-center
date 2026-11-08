"""Web view models: grouping by local day, load, heat, deadlines and link safety."""

from datetime import UTC, date, datetime, timedelta

import pytest

from builders import NOW, make_event
from command_center.web.views import (
    HEAT_LEVELS,
    TOP_DEADLINES,
    heat_level,
    month_view,
    safe_link,
    to_row,
    top_deadlines,
    week_view,
)
from web_rig import DENVER

SAT = date(2026, 11, 7)


def test_week_puts_an_evening_event_on_its_local_day_not_its_utc_day() -> None:
    evening = make_event(
        id="e", start=datetime(2026, 11, 8, 3, 0, tzinfo=UTC), urgency=10
    )  # Sat 20:00

    columns = week_view([evening], SAT, SAT, DENVER).columns

    assert [(c.day, c.load) for c in columns if c.load] == [(SAT, 10)]


def test_week_load_is_the_sum_of_urgency_per_day() -> None:
    a = make_event(id="a", start=NOW, urgency=40)
    b = make_event(id="b", start=NOW + timedelta(hours=2), urgency=25)
    other = make_event(id="c", start=NOW + timedelta(days=1), urgency=7)

    columns = week_view([a, b, other], SAT, SAT, DENVER).columns

    assert [c.load for c in columns] == [0, 0, 0, 0, 0, 65, 7]


def test_week_has_seven_days_starting_monday() -> None:
    columns = week_view([], SAT, SAT, DENVER).columns

    assert [c.day.weekday() for c in columns] == [0, 1, 2, 3, 4, 5, 6]


def test_week_shows_an_item_that_began_before_the_week_on_the_first_day_as_ongoing() -> None:
    trip = make_event(id="trip", start=NOW - timedelta(days=20), end=NOW + timedelta(days=1))

    first = week_view([trip], SAT, SAT, DENVER).columns[0]

    assert [(r.title, r.when) for r in first.rows] == [("Title", "Ongoing")]


def test_week_leaves_weather_out_of_the_columns() -> None:
    sun = make_event(id="w", kind="weather", start=NOW)

    assert all(not c.rows for c in week_view([sun], SAT, SAT, DENVER).columns)


def test_month_grid_is_whole_weeks_and_only_counts_the_month() -> None:
    inside = make_event(id="in", start=NOW, urgency=30)

    weeks = month_view([inside], SAT, SAT, DENVER).weeks

    assert {len(w) for w in weeks} == {7}
    assert sum(c.load for w in weeks for c in w if not c.in_month) == 0


def test_heat_is_proportional_to_the_busiest_day() -> None:
    busy = make_event(id="busy", start=NOW, urgency=80)
    quiet = make_event(id="quiet", start=NOW + timedelta(days=1), urgency=10)

    cells = {c.day: c for w in month_view([busy, quiet], SAT, SAT, DENVER).weeks for c in w}

    assert (cells[SAT].level, cells[date(2026, 11, 8)].level, cells[date(2026, 11, 9)].level) == (
        HEAT_LEVELS,
        1,
        0,
    )


@pytest.mark.parametrize(
    ("load", "busiest", "level"), [(0, 0, 0), (0, 50, 0), (50, 50, 4), (13, 50, 2)]
)
def test_heat_level(load: int, busiest: int, level: int) -> None:
    assert heat_level(load, busiest) == level


def test_top_deadlines_skip_done_work_and_order_by_urgency() -> None:
    done = make_event(id="d", kind="assignment", due=NOW, urgency=100, status="done")
    soon = make_event(id="s", kind="assignment", due=NOW, urgency=90, title="Soon")
    later = make_event(
        id="l", kind="assignment", due=NOW + timedelta(days=5), urgency=40, title="Later"
    )
    undated_event = make_event(id="u", start=NOW, urgency=99)

    result = top_deadlines([later, done, undated_event, soon])

    assert [e.title for e in result] == ["Soon", "Later"]


def test_top_deadlines_are_capped() -> None:
    many = [make_event(id=f"a{i}", kind="assignment", due=NOW, urgency=i) for i in range(20)]

    assert len(top_deadlines(many)) == TOP_DEADLINES


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ("https://canvas.example/a", "https://canvas.example/a"),
        ("http://canvas.example/a", "http://canvas.example/a"),
        ("javascript:alert(1)", None),
        ("JaVaScRiPt:alert(1)", None),
        ("data:text/html,<script>1</script>", None),
        ("//evil.example/x", None),
        ("http://[broken", None),
        ("", None),
        (None, None),
    ],
)
def test_safe_link_allows_only_http_urls(link: str | None, expected: str | None) -> None:
    assert safe_link(link) == expected


def test_row_labels_a_due_item_with_its_local_due_time() -> None:
    due = make_event(id="due", kind="assignment", due=NOW + timedelta(hours=10))  # 15:00 local

    assert to_row(due, DENVER, SAT).when == "Due 15:00"


def test_row_for_an_undated_item_has_no_time() -> None:
    assert to_row(make_event(id="u"), DENVER, SAT).when == ""
