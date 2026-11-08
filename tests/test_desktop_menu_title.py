"""The menu-bar title: the next open deadline, worded for a glance. No rumps involved."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from builders import NOW, make_event
from command_center.desktop.menu_title import (
    IDLE_TITLE,
    OFFLINE_TITLE,
    TITLE_LIMIT,
    describe_due,
    menu_title,
    next_deadline,
)

DENVER = ZoneInfo("America/Denver")  # NOW is 05:00 on Saturday 2026-11-07 here


def assignment(event_id: str, due: datetime, *, status: str = "open", title: str = "Essay"):  # noqa: ANN201
    return make_event(id=event_id, kind="assignment", title=title, due=due, status=status)


def test_the_next_deadline_is_the_soonest_open_assignment() -> None:
    later = assignment("b", NOW + timedelta(days=2))
    sooner = assignment("a", NOW + timedelta(hours=3))
    assert next_deadline([later, sooner], NOW) == sooner


def test_submitted_work_is_not_a_deadline() -> None:
    done = assignment("a", NOW + timedelta(hours=1), status="done")
    open_ = assignment("b", NOW + timedelta(days=1))
    assert next_deadline([done, open_], NOW) == open_


def test_a_deadline_already_past_is_not_next() -> None:
    assert next_deadline([assignment("a", NOW - timedelta(minutes=1))], NOW) is None


def test_calendar_events_and_email_are_not_deadlines() -> None:
    event = make_event(id="e", kind="event", start=NOW + timedelta(hours=1))
    mail = make_event(id="m", kind="email", due=NOW + timedelta(hours=1))
    assert next_deadline([event, mail], NOW) is None


def test_an_assignment_without_a_due_date_is_skipped() -> None:
    undated = make_event(id="u", kind="assignment", due=None, status="open")
    assert next_deadline([undated], NOW) is None


def test_ties_break_by_id_so_the_title_does_not_flicker() -> None:
    due = NOW + timedelta(hours=2)
    first, second = assignment("a", due), assignment("b", due)
    assert next_deadline([second, first], NOW) == first


def test_under_an_hour_is_in_minutes() -> None:
    assert describe_due(NOW + timedelta(minutes=25), NOW, DENVER) == "in 25m"


def test_a_partial_minute_rounds_up() -> None:
    assert describe_due(NOW + timedelta(seconds=61), NOW, DENVER) == "in 2m"


def test_later_today_is_the_clock_time_in_the_local_zone() -> None:
    assert describe_due(NOW + timedelta(hours=5), NOW, DENVER) == "today 10:00"


def test_tomorrow_is_named() -> None:
    assert describe_due(NOW + timedelta(days=1), NOW, DENVER) == "tomorrow 05:00"


def test_within_a_week_is_the_weekday() -> None:
    assert describe_due(NOW + timedelta(days=3), NOW, DENVER) == "Tue 05:00"


def test_further_out_is_the_date() -> None:
    assert describe_due(NOW + timedelta(days=20), NOW, DENVER) == "27 Nov"


def test_a_deadline_that_has_just_passed_reads_due_now() -> None:
    assert describe_due(NOW - timedelta(seconds=5), NOW, DENVER) == "due now"


def test_the_title_joins_the_deadline_and_when() -> None:
    event = assignment("a", NOW + timedelta(hours=5), title="Essay 2")
    assert menu_title(event, NOW, DENVER) == "Essay 2 · today 10:00"


def test_a_long_title_is_cut_with_an_ellipsis() -> None:
    event = assignment("a", NOW + timedelta(hours=5), title="x" * 200)
    title = menu_title(event, NOW, DENVER)
    assert title.startswith("x" * (TITLE_LIMIT - 1) + "…")
    assert len(title) < 60


def test_newlines_and_runs_of_space_are_collapsed() -> None:
    event = assignment("a", NOW + timedelta(hours=5), title="Lab\n\n  report\t3")
    assert menu_title(event, NOW, DENVER) == "Lab report 3 · today 10:00"


def test_no_deadline_shows_the_idle_title() -> None:
    assert menu_title(None, NOW, DENVER) == IDLE_TITLE


def test_the_offline_title_is_distinct() -> None:
    assert OFFLINE_TITLE != IDLE_TITLE
