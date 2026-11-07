"""Manual sync trigger."""

from fastapi import APIRouter

from command_center.api.deps import ContainerDep
from command_center.services.models import SyncState

router = APIRouter(prefix="/v1", tags=["sync"])


@router.post("/sync", summary="Sync every source now")
async def sync_all(container: ContainerDep) -> list[SyncState]:
    """Sync all sources and return each one's new state; a failing source does not raise."""
    return await container.sync.sync_all()
