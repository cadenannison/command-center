"""The slice of the Canvas REST responses the adapter reads, and the parse that guards it."""

from collections.abc import Sequence

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from command_center.core.errors import FatalError


class Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class Course(Model):
    id: int
    name: str | None = None
    course_code: str | None = None
    access_restricted_by_date: bool = False


class Submission(Model):
    workflow_state: str | None = None


class Assignment(Model):
    id: int
    name: str | None = None
    due_at: AwareDatetime | None = None
    html_url: str | None = None
    submission: Submission | None = None


class CalendarEvent(Model):
    id: int
    title: str | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    html_url: str | None = None
    workflow_state: str | None = None


class Plannable(Model):
    title: str | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    todo_date: AwareDatetime | None = None
    due_at: AwareDatetime | None = None


class PlannerItem(Model):
    plannable_type: str
    plannable_id: str | int
    plannable: Plannable
    html_url: str | None = None


def parse_rows[M: Model](rows: Sequence[object], model: type[M], what: str) -> list[M]:
    try:
        return [model.model_validate(row) for row in rows]
    except ValidationError:
        # The error text quotes the offending input, so it is dropped (decision 0023).
        msg = f"Failed to read Canvas {what}: the response had an unexpected shape"
        raise FatalError(msg) from None
