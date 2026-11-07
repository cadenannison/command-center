"""Read routes: events in a window, the day/week/month agenda and the attention list."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.exceptions import RequestValidationError
from pydantic import AwareDatetime, ValidationError

from command_center.api.deps import ContainerDep
from command_center.api.errors import INVALID_REQUEST
from command_center.core.schema import Event
from command_center.core.windows import TimeWindow

router = APIRouter(prefix="/v1", tags=["agenda"])

Period = Literal["day", "week", "month"]


@router.get("/events", summary="Events in a time window", responses=INVALID_REQUEST)
async def list_events(
    container: ContainerDep,
    start: Annotated[AwareDatetime, Query(alias="from")],
    end: Annotated[AwareDatetime, Query(alias="to")],
) -> list[Event]:
    """Events overlapping [from, to), scored now. Both bounds carry a timezone (use Z or %2B)."""
    try:
        window = TimeWindow(start=start, end=end)
    except ValidationError:
        issue = {
            "type": "value_error",
            "loc": ("query", "to"),
            "msg": "`to` must be after `from`",
            "input": None,
        }
        raise RequestValidationError([issue]) from None
    return await container.agenda.between(window)


@router.get(
    "/agenda/{period}", summary="Agenda for a day, week or month", responses=INVALID_REQUEST
)
async def agenda(
    container: ContainerDep,
    period: Period,
    day: Annotated[date, Query(alias="date")],
) -> list[Event]:
    """Events in the day, Monday-based week or month containing `date`, in the user's timezone."""
    service = container.agenda
    views = {"day": service.day, "week": service.week, "month": service.month}
    return await views[period](day)


@router.get("/attention", summary="Items needing attention")
async def attention(container: ContainerDep) -> list[Event]:
    """Urgent items (urgency 70+) and owed or overdue email, most urgent first."""
    return await container.agenda.attention()
