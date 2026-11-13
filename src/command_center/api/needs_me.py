"""What needs the user's attention across kinds, for the Needs me widget (decisions 0385, 0386)."""

from fastapi import APIRouter

from command_center.api.deps import ContainerDep
from command_center.core.needs_me import NeedsMeItem

router = APIRouter(prefix="/v1", tags=["needs-me"])


@router.get("/needs-me", summary="What needs your attention now, across tasks, mail and events")
async def list_needs_me(container: ContainerDep) -> list[NeedsMeItem]:
    """At most 20 items, priority descending, then `at` ascending, then id. Read-only.

    `at` is the due time, else the start. Done items are left out. `link` is the source's own
    link or null.
    """
    return await container.agenda.needs_me()
