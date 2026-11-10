"""Check-off, notes and your own tasks on the pages (HTMX fragments; decisions 0150 to 0153).

Every route calls one `ItemService` method and answers with the row drawn again. The browser
swaps that row in place, so there is no full reload. Without an item service every route is 404.
"""

from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from command_center.core.ledger import ItemMark
from command_center.core.schema import Event
from command_center.services.container import Container
from command_center.services.items import ItemNotFoundError, ItemService, NotLocalItemError
from command_center.web.item_view import CONTEXTS, NewTaskForm, needs_mark
from command_center.web.render import Renderer
from command_center.web.task_form import TaskFormError, new_task, task_patch
from command_center.web.views import to_row

NO_ITEMS = "Items are not enabled"
NO_SUCH_ITEM = "No such item"
NOT_LOCAL = "Only your own tasks can be changed or deleted"
NOTE_SAVED = "Note saved."
NOTE_DELETED = "Note deleted."
TASK_SAVED = "Task saved."

Context = Literal["agenda", "attention", "week", "deadline"]


@dataclass(frozen=True)
class Place:
    """Where the row was clicked: the page list, and how its time was labelled."""

    ctx: Context = "agenda"
    day: date | None = None
    dated: bool = False


@dataclass(frozen=True)
class TaskFormData:
    """The fields of the New task and Edit task forms, as typed."""

    title: str
    due_date: str
    due_time: str
    label: str


def place(
    ctx: Annotated[Context, Query()] = "agenda",
    day: Annotated[date | None, Query()] = None,
    dated: Annotated[bool, Query()] = False,  # noqa: FBT002
) -> Place:
    """The row's place, read from the query string the row's own buttons carry."""
    return Place(ctx, day, dated)


def task_form(
    title: Annotated[str, Form()] = "",
    due_date: Annotated[str, Form()] = "",
    due_time: Annotated[str, Form()] = "",
    label: Annotated[str, Form()] = "",
) -> TaskFormData:
    """The task form fields from the request body."""
    return TaskFormData(title, due_date, due_time, label)


Where = Annotated[Place, Depends(place)]
Typed = Annotated[TaskFormData, Depends(task_form)]


async def page_marks(
    container: Container, *event_lists: Sequence[Event]
) -> dict[str, ItemMark] | None:
    """The ledger marks the pages need, or None when there is no item service (no controls)."""
    if container.items is None:
        return None
    wanted = sorted({e.id for events in event_lists for e in events if needs_mark(e)})
    return await container.items.marks(wanted)


@contextmanager
def _translated() -> Generator[None]:
    """Turn the service's item errors into the HTTP answers the browser gets."""
    try:
        yield
    except ItemNotFoundError:
        raise HTTPException(status_code=404, detail=NO_SUCH_ITEM) from None
    except NotLocalItemError:
        raise HTTPException(status_code=409, detail=NOT_LOCAL) from None


class Drawer:
    """Draws one item's row again, or the notice that it is gone."""

    def __init__(self, renderer: Renderer) -> None:
        self._renderer = renderer

    @staticmethod
    def items(services: Container) -> ItemService:
        """The item service; 404 while there is none."""
        if services.items is None:
            raise HTTPException(status_code=404, detail=NO_ITEMS)
        return services.items

    async def row(  # noqa: PLR0913  (one keyword per thing a reply may add to the row)
        self,
        request: Request,
        services: Container,
        item_id: str,
        where: Place,
        *,
        message: str = "",
        ok: bool = True,
        opened: bool = False,
        typed_note: str | None = None,
        drop: tuple[str, ...] = (),
    ) -> HTMLResponse:
        """The row as it is now, plus out-of-band removals of the copies named in `drop`."""
        items = self.items(services)
        with _translated():
            event = await items.get(item_id)
        marks = await items.marks([item_id]) if needs_mark(event) else {}
        agenda = services.agenda
        row = to_row(
            event,
            agenda.tz,
            where.day,
            dated=where.dated,
            ctx=where.ctx,
            now=agenda.now(),
            marks=marks,
        )
        context = {
            "r": row,
            "item_id": item_id,
            "message": message,
            "ok": ok,
            "opened": opened,
            "typed_note": typed_note,
            "drop": drop,
        }
        return self._renderer.render(request, "_item_row.html", context)

    def gone(self, request: Request, item_id: str, drop: tuple[str, ...]) -> HTMLResponse:
        """No row: the clicked one is removed by the swap, the other copies by `drop`."""
        context = {"r": None, "item_id": item_id, "drop": drop}
        return self._renderer.render(request, "_item_row.html", context)


def _done_routes(get_container: Callable[..., Container], drawer: Drawer) -> APIRouter:
    router = APIRouter()

    @router.post("/items/{item_id}/done", response_class=HTMLResponse)
    async def check_off(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        item_id: str,
        where: Where,
    ) -> HTMLResponse:
        with _translated():
            await drawer.items(services).check_off(item_id)
        # The other copy in "needs attention" goes now; a done item has no priority (decision 0152).
        drop = () if where.ctx == "attention" else ("attention",)
        return await drawer.row(request, services, item_id, where, drop=drop)

    @router.delete("/items/{item_id}/done", response_class=HTMLResponse)
    async def undo(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        item_id: str,
        where: Where,
    ) -> HTMLResponse:
        with _translated():
            await drawer.items(services).undo(item_id)
        return await drawer.row(request, services, item_id, where)

    return router


def _note_routes(get_container: Callable[..., Container], drawer: Drawer) -> APIRouter:
    router = APIRouter()

    @router.put("/items/{item_id}/notes", response_class=HTMLResponse)
    async def save_note(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        item_id: str,
        where: Where,
        text: Annotated[str, Form()] = "",
    ) -> HTMLResponse:
        try:
            with _translated():
                await drawer.items(services).set_note(item_id, text)
        except ValidationError as exc:
            # The typed text stays in the box; the message is the model's fixed text.
            return await drawer.row(
                request,
                services,
                item_id,
                where,
                message=_first_message(exc),
                ok=False,
                opened=True,
                typed_note=text,
            )
        return await drawer.row(request, services, item_id, where, message=NOTE_SAVED, opened=True)

    @router.delete("/items/{item_id}/notes", response_class=HTMLResponse)
    async def delete_note(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        item_id: str,
        where: Where,
    ) -> HTMLResponse:
        with _translated():
            await drawer.items(services).clear_note(item_id)
        return await drawer.row(
            request, services, item_id, where, message=NOTE_DELETED, opened=True
        )

    return router


def _task_routes(get_container: Callable[..., Container], drawer: Drawer) -> APIRouter:
    router = APIRouter()

    @router.patch("/items/{item_id}", response_class=HTMLResponse)
    async def edit_task(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        item_id: str,
        where: Where,
        form: Typed,
    ) -> HTMLResponse:
        items = drawer.items(services)
        try:
            patch = task_patch(*_fields(form), services.agenda.tz)
            with _translated():
                await items.update_task(item_id, patch)
        except TaskFormError as exc:
            return await drawer.row(
                request, services, item_id, where, message=str(exc), ok=False, opened=True
            )
        return await drawer.row(request, services, item_id, where, message=TASK_SAVED, opened=True)

    @router.delete("/items/{item_id}", response_class=HTMLResponse)
    async def delete_task(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        item_id: str,
        where: Where,
    ) -> HTMLResponse:
        with _translated():
            await drawer.items(services).delete_task(item_id)
        return drawer.gone(request, item_id, tuple(c for c in CONTEXTS if c != where.ctx))

    return router


def _create_route(
    get_container: Callable[..., Container], drawer: Drawer, renderer: Renderer
) -> APIRouter:
    router = APIRouter()

    @router.post("/tasks", response_class=HTMLResponse)
    async def create_task(
        request: Request, services: Annotated[Container, Depends(get_container)], form: Typed
    ) -> Response:
        items = drawer.items(services)
        tz = services.agenda.tz
        try:
            task = new_task(*_fields(form), tz)
        except TaskFormError as exc:
            retry = NewTaskForm(form.due_date, form.title, form.due_time, form.label, str(exc))
            return renderer.render(request, "_new_task.html", {"nt": retry})
        created = await items.create_task(task)
        # Land on the day the task is due, where it is in the agenda (decision 0153).
        shown = created.due.astimezone(tz).date() if created.due else services.agenda.today()
        return Response(status_code=200, headers={"HX-Redirect": f"/?date={shown.isoformat()}"})

    return router


def item_router(get_container: Callable[..., Container], renderer: Renderer) -> APIRouter:
    """The item and task routes; mounted on the web router, so every write needs the CSRF token."""
    drawer = Drawer(renderer)
    router = APIRouter()
    router.include_router(_done_routes(get_container, drawer))
    router.include_router(_note_routes(get_container, drawer))
    router.include_router(_task_routes(get_container, drawer))
    router.include_router(_create_route(get_container, drawer, renderer))
    return router


def _fields(form: TaskFormData) -> tuple[str, str, str, str]:
    return form.title, form.due_date, form.due_time, form.label


def _first_message(exc: ValidationError) -> str:
    errors = exc.errors(include_input=False, include_url=False)
    return str(errors[0]["msg"]).capitalize() + "." if errors else "Not valid."
