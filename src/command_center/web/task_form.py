"""Turns the New task and Edit task forms into core inputs. Pure: the timezone comes in.

The due date and time are typed in the settings timezone and stored as an instant. Every message
is a fixed text; nothing the user typed is echoed back (decision 0023).
"""

from datetime import date, datetime, time, tzinfo

from pydantic import ValidationError

from command_center.core.ledger import TaskInput, TaskPatch

DUE_REQUIRED = "Enter a due date and a due time."
DUE_INVALID = "The due date or time is not valid."


class TaskFormError(ValueError):
    """The form cannot become a task; the message is safe to show."""


def parse_due(due_date: str, due_time: str, tz: tzinfo) -> datetime:
    """The instant for a date (YYYY-MM-DD) and a time (HH:MM) read in tz."""
    if not due_date.strip() or not due_time.strip():
        raise TaskFormError(DUE_REQUIRED)
    try:
        day = date.fromisoformat(due_date.strip())
        clock = time.fromisoformat(due_time.strip())
    except ValueError:
        raise TaskFormError(DUE_INVALID) from None
    if clock.tzinfo is not None:
        raise TaskFormError(DUE_INVALID)
    return datetime.combine(day, clock, tzinfo=tz)


def new_task(title: str, due_date: str, due_time: str, label: str, tz: tzinfo) -> TaskInput:
    """A TaskInput from the New task form."""
    due = parse_due(due_date, due_time, tz)
    try:
        return TaskInput(title=title, due=due, label=label)
    except ValidationError as exc:
        raise TaskFormError(_message(exc)) from None


def task_patch(title: str, due_date: str, due_time: str, label: str, tz: tzinfo) -> TaskPatch:
    """A TaskPatch from the Edit task form: every field is sent, a blank label removes it."""
    due = parse_due(due_date, due_time, tz)
    try:
        return TaskPatch(title=title, due=due, label=label)
    except ValidationError as exc:
        raise TaskFormError(_message(exc)) from None


def _message(exc: ValidationError) -> str:
    texts = {error["msg"] for error in exc.errors(include_input=False, include_url=False)}
    return "; ".join(sorted(texts)).capitalize() + "."
