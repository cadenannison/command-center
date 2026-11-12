"""The ranked task list the Tasks widget reads (decisions 0332, 0371). Read-only."""

from fastapi import APIRouter

from command_center.api.deps import ContainerDep
from command_center.core.urgency import TaskItem

router = APIRouter(prefix="/v1", tags=["tasks"])


@router.get("/tasks", summary="Tasks ranked by urgency, with the reasons")
async def list_tasks(container: ContainerDep) -> list[TaskItem]:
    """Tasks, assignments and email in the sync horizon: priority 1-10 and why, most urgent first.

    Sorted by `priority` descending, then `due` ascending (no due time last). Done items stay in
    the list with `done` true and the lowest priority. `link` is the source's own link or null.
    """
    return await container.agenda.tasks()
