"""The opt-in daily summary, always mounted; 404 while summaries are off (decisions 0037, 0053)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from command_center.api.deps import ContainerDep
from command_center.api.errors import INVALID_REQUEST, NOT_FOUND
from command_center.services.summary import SummaryResult

router = APIRouter(prefix="/v1", tags=["summary"])

SUMMARY_OFF = "Summaries are off"


@router.get(
    "/summary",
    summary="The day's AI summary",
    responses={**NOT_FOUND, **INVALID_REQUEST},
)
async def get_summary(
    container: ContainerDep,
    day: Annotated[date, Query(alias="date")],
) -> SummaryResult:
    """The summary for `date`, with the `provider` it came from and whether it was `cached`.

    404 when summaries are off (the default). A provider failure never fails the request: the
    last stored summary (`provider` "stored") or a built-in one (`provider` "template") is returned.
    """
    service = await container.summary_service()
    if service is None:
        raise HTTPException(status_code=404, detail=SUMMARY_OFF)
    return await service.get(day)
