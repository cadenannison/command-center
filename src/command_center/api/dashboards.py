"""Dashboards and display settings (decisions 0355 to 0358).

Always mounted; every route answers 404 while the container has no dashboard service. Reads are
open to a paired phone; every write is loopback only (`api/policy.py`). A write names the revision
it was based on in `If-Match` (`"3"`); a mismatch is 409 and nothing is written. Responses carry
the revision as `ETag` and are `no-store`.
"""

import re
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Path, Response

from command_center.api.deps import ContainerDep
from command_center.api.errors import INVALID_REQUEST, NOT_FOUND, ErrorBody
from command_center.core.dashboards import (
    ID_PATTERN,
    Dashboard,
    DashboardInput,
    DashboardLimitError,
    DashboardNotFoundError,
    DashboardSetError,
    DisplayInput,
    DisplaySettings,
    ReorderInput,
    RevisionConflictError,
)
from command_center.services.container import Container
from command_center.services.dashboards import DashboardService

NO_STORE = {"Cache-Control": "no-store"}

router = APIRouter(prefix="/v1", tags=["dashboards"])

OFF = "Dashboards are not enabled"
NO_SUCH = "No such dashboard"
CONFLICT = "The revision is out of date; reload and try again"
LIMIT = "There are too many dashboards"
STALE_SET = "The dashboards changed; reload and try again"
NEEDS_REVISION = "If-Match is required"
BAD_REVISION = 'If-Match must be a revision such as "3"'

_REVISION = re.compile(r'^"?([0-9]{1,9})"?$')
_CONFLICT: dict[int | str, dict[str, Any]] = {409: {"model": ErrorBody}}
_PRECONDITION: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorBody},
    428: {"model": ErrorBody},
}
_WRITE = {**NOT_FOUND, **INVALID_REQUEST, **_CONFLICT, **_PRECONDITION}
IfMatch = Annotated[
    str | None,
    Header(description='The revision this change is based on, as `"3"`. Required on a replace.'),
]


DashboardId = Annotated[str, Path(pattern=ID_PATTERN)]


def _service(container: Container) -> DashboardService:
    if container.dashboards is None:
        raise HTTPException(status_code=404, detail=OFF)
    return container.dashboards


def _revision(value: str | None) -> int:
    if value is None:
        raise HTTPException(status_code=428, detail=NEEDS_REVISION)
    match = _REVISION.fullmatch(value.strip())
    if match is None:
        raise HTTPException(status_code=400, detail=BAD_REVISION)
    return int(match.group(1))


def _headers(response: Response, revision: int | None = None) -> None:
    response.headers["Cache-Control"] = "no-store"
    if revision is not None:
        response.headers["ETag"] = f'"{revision}"'


@router.get("/dashboards", summary="List dashboards", responses=NOT_FOUND)
async def list_dashboards(container: ContainerDep, response: Response) -> list[Dashboard]:
    """Every dashboard in position order, each with its layout and revision."""
    _headers(response)
    return await _service(container).list_all()


@router.post(
    "/dashboards",
    status_code=201,
    summary="Create a dashboard",
    responses={**NOT_FOUND, **INVALID_REQUEST, **_CONFLICT},
)
async def create_dashboard(
    container: ContainerDep, body: DashboardInput, response: Response
) -> Dashboard:
    """Add a dashboard in the last position, at revision 1. 409 at 20 dashboards."""
    try:
        created = await _service(container).add(body)
    except DashboardLimitError:
        raise HTTPException(status_code=409, detail=LIMIT) from None
    except RevisionConflictError:
        raise HTTPException(status_code=409, detail=CONFLICT) from None
    _headers(response, created.revision)
    return created


@router.put(
    "/dashboards/order",
    summary="Reorder dashboards",
    responses={**NOT_FOUND, **INVALID_REQUEST, **_CONFLICT},
)
async def reorder_dashboards(
    container: ContainerDep, body: ReorderInput, response: Response
) -> list[Dashboard]:
    """Set the order. `ids` must be every dashboard exactly once, else 409 (a stale list)."""
    _headers(response)
    try:
        return await _service(container).reorder(body.ids)
    except DashboardSetError:
        raise HTTPException(status_code=409, detail=STALE_SET) from None


@router.get(
    "/dashboards/{dashboard_id}",
    summary="Get a dashboard",
    responses={**NOT_FOUND, **INVALID_REQUEST},
)
async def get_dashboard(
    container: ContainerDep, dashboard_id: DashboardId, response: Response
) -> Dashboard:
    """One dashboard; its revision is also the `ETag`."""
    try:
        found = await _service(container).get(dashboard_id)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH) from None
    _headers(response, found.revision)
    return found


@router.put("/dashboards/{dashboard_id}", summary="Replace a dashboard", responses=_WRITE)
async def replace_dashboard(
    container: ContainerDep,
    dashboard_id: DashboardId,
    body: DashboardInput,
    response: Response,
    if_match: IfMatch = None,
) -> Dashboard:
    """Replace name and layout. 409 when `If-Match` is not the stored revision."""
    revision = _revision(if_match)
    try:
        saved = await _service(container).replace(dashboard_id, revision, body)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH) from None
    except RevisionConflictError:
        raise HTTPException(status_code=409, detail=CONFLICT) from None
    _headers(response, saved.revision)
    return saved


@router.delete(
    "/dashboards/{dashboard_id}", status_code=204, summary="Delete a dashboard", responses=_WRITE
)
async def delete_dashboard(
    container: ContainerDep, dashboard_id: DashboardId, if_match: IfMatch = None
) -> Response:
    """Delete a dashboard. 409 when `If-Match` is not the stored revision."""
    revision = _revision(if_match)
    try:
        await _service(container).delete(dashboard_id, revision)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH) from None
    except RevisionConflictError:
        raise HTTPException(status_code=409, detail=CONFLICT) from None
    return Response(status_code=204, headers=NO_STORE)


@router.get("/display-settings", summary="Get the display settings", responses=NOT_FOUND)
async def get_display_settings(container: ContainerDep, response: Response) -> DisplaySettings:
    """The stored display settings, or the defaults at revision 0 when none are saved."""
    current = await _service(container).display()
    _headers(response, current.revision)
    return current


@router.put(
    "/display-settings",
    summary="Replace the display settings",
    responses={**NOT_FOUND, **INVALID_REQUEST, **_CONFLICT, **_PRECONDITION},
)
async def replace_display_settings(
    container: ContainerDep, body: DisplayInput, response: Response, if_match: IfMatch = None
) -> DisplaySettings:
    """Replace every setting. `If-Match` is the revision read (`"0"` before the first save)."""
    revision = _revision(if_match)
    try:
        saved = await _service(container).replace_display(revision, body)
    except RevisionConflictError:
        raise HTTPException(status_code=409, detail=CONFLICT) from None
    _headers(response, saved.revision)
    return saved
