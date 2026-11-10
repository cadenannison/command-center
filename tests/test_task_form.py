"""The task form parser: the typed date and time are read in the settings timezone."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from command_center.core.ledger import MAX_LABEL, MAX_TITLE
from command_center.web.task_form import (
    DUE_INVALID,
    DUE_REQUIRED,
    TaskFormError,
    new_task,
    parse_due,
    task_patch,
)

DENVER = ZoneInfo("America/Denver")


def test_a_time_in_winter_is_seven_hours_behind_utc() -> None:
    assert parse_due("2026-11-07", "15:00", DENVER).astimezone(UTC) == datetime(
        2026, 11, 7, 22, 0, tzinfo=UTC
    )


def test_a_time_in_summer_is_six_hours_behind_utc() -> None:
    assert parse_due("2026-07-07", "15:00", DENVER).astimezone(UTC) == datetime(
        2026, 7, 7, 21, 0, tzinfo=UTC
    )


def test_the_day_clocks_go_back_the_same_wall_time_is_still_the_wall_time_typed() -> None:
    due = parse_due("2026-11-01", "12:00", DENVER)

    assert (due.hour, due.minute) == (12, 0)
    assert due.astimezone(UTC) == datetime(2026, 11, 1, 19, 0, tzinfo=UTC)


@pytest.mark.parametrize(("due_date", "due_time"), [("", "10:00"), ("2026-11-07", ""), ("  ", " ")])
def test_a_blank_date_or_time_asks_for_both(due_date: str, due_time: str) -> None:
    with pytest.raises(TaskFormError, match=DUE_REQUIRED):
        parse_due(due_date, due_time, DENVER)


@pytest.mark.parametrize(
    ("due_date", "due_time"),
    [
        ("2026-02-30", "10:00"),
        ("soon", "10:00"),
        ("2026-11-07", "24:00"),
        ("2026-11-07", "10:00+02:00"),
    ],
)
def test_an_impossible_date_or_time_is_not_valid(due_date: str, due_time: str) -> None:
    with pytest.raises(TaskFormError, match=DUE_INVALID):
        parse_due(due_date, due_time, DENVER)


def test_new_task_carries_the_title_due_and_label() -> None:
    task = new_task("Essay", "2026-11-07", "15:00", "BIO", DENVER)

    assert (task.title, task.label) == ("Essay", "BIO")
    assert task.due == datetime(2026, 11, 7, 22, 0, tzinfo=UTC)


def test_a_title_over_the_limit_gets_the_models_fixed_message_without_the_title() -> None:
    title = "secret-title-" + "t" * MAX_TITLE

    with pytest.raises(TaskFormError) as caught:
        new_task(title, "2026-11-07", "15:00", "", DENVER)

    assert "secret-title" not in str(caught.value)
    assert str(caught.value) == "Title must be 1 to 200 characters."


def test_task_patch_gives_every_field_and_a_blank_label_is_given_as_none_to_remove_it() -> None:
    patch = task_patch("Essay", "2026-11-07", "15:00", "", DENVER)

    assert patch.model_fields_set == {"title", "due", "label"}
    assert patch.label is None
    assert patch.title == "Essay"


@given(
    day=st.dates(min_value=date(2001, 1, 1), max_value=date(2099, 12, 31)),
    clock=st.times(),
)
def test_the_stored_instant_always_reads_back_as_the_typed_wall_time(
    day: date, clock: time
) -> None:
    clock = clock.replace(second=0, microsecond=0)

    due = parse_due(day.isoformat(), clock.strftime("%H:%M"), DENVER)

    local = due.astimezone(DENVER)
    assert due.utcoffset() is not None
    assert local.date() == day
    assert (local.hour, local.minute) == (clock.hour, clock.minute) or _in_a_gap(local, clock)


@given(
    title=st.text(max_size=400),
    label=st.text(max_size=200),
)
def test_a_rejected_form_never_echoes_what_was_typed(title: str, label: str) -> None:
    try:
        new_task(title, "2026-11-07", "15:00", label, DENVER)
    except TaskFormError as exc:
        message = str(exc)
        assert len(message) < 80
        for typed in (title.strip(), label.strip()):
            if len(typed) > 3:
                assert typed not in message
    else:
        assert 1 <= len(title.strip()) <= MAX_TITLE
        assert len(label.strip()) <= MAX_LABEL


def _in_a_gap(local: datetime, clock: time) -> bool:
    """On the spring-forward day a skipped wall time (02:30) lands an hour later."""
    return local.hour == clock.hour + 1
