"""Manual sync trigger."""

from fastapi import APIRouter

from command_center.api.deps import ContainerDep
from command_center.services.models import SyncState

router = APIRouter(prefix="/v1", tags=["sync"])


@router.post("/sync", summary="Sync every source now")
async def sync_all(container: ContainerDep) -> list[SyncState]:
    """Sync all sources and return each one's new state; a failing source does not raise.

    In distributed mode nothing is fetched here: a job is queued for every connected source and
    each is returned as "syncing"; the other sources are returned as last recorded. Read the
    results from `GET /v1/settings` once the workers have reported.
    """
    return await container.sync.sync_all()
