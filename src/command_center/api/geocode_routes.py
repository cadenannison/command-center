"""City search for the weather form: candidates for a name, never a pick (decision 0180)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import StringConstraints

from command_center.api.deps import ContainerDep
from command_center.api.errors import INVALID_REQUEST, ErrorBody
from command_center.core.geocode import (
    MAX_QUERY_LENGTH,
    MIN_QUERY_LENGTH,
    GeocodeCandidate,
)
from command_center.services.errors import GeocodeRateLimitedError, GeocodeUnavailableError

router = APIRouter(prefix="/v1", tags=["weather"])

NOT_AVAILABLE = "City search is not available"
_NO_STORE = {"Cache-Control": "no-store"}

SearchText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=MIN_QUERY_LENGTH, max_length=MAX_QUERY_LENGTH
    ),
]

_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorBody, "description": NOT_AVAILABLE},
    429: {
        "model": ErrorBody,
        "description": "Too many searches in the last minute; wait Retry-After seconds",
        "headers": {"Retry-After": {"schema": {"type": "integer"}}},
    },
    502: {"model": ErrorBody, "description": "Open-Meteo could not answer; the detail is redacted"},
}


@router.get(
    "/geocode",
    summary="Find places by city name",
    responses={**_RESPONSES, **INVALID_REQUEST},
)
async def geocode(
    container: ContainerDep, response: Response, q: Annotated[SearchText, Query()]
) -> list[GeocodeCandidate]:
    """Up to 5 candidates (`name`, `region`, `country`, `latitude`, `longitude`, `population`).

    Open-Meteo's order is kept and nothing is picked for the caller: the user chooses one and the
    stored `latitude` and `longitude` are then set as usual. Loopback only: a paired phone gets
    403. At most 10 searches a minute (429 with `Retry-After`). The query text is never logged.
    """
    if container.geocode is None:
        raise HTTPException(status_code=404, detail=NOT_AVAILABLE)
    try:
        found = await container.geocode.search(q)
    except GeocodeRateLimitedError as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds), **_NO_STORE},
        ) from None
    except GeocodeUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc), headers=_NO_STORE) from None
    response.headers.update(_NO_STORE)
    return found
