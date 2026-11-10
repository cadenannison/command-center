"""Today, Week and Month."""

from collections.abc import Callable
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from command_center.services.container import Container
from command_center.web.item_routes import page_marks
from command_center.web.item_view import NewTaskForm
from command_center.web.render import Renderer
from command_center.web.summary import summary_card, summary_context
from command_center.web.views import month_view, today_view, week_view

DayParam = Annotated[date | None, Query(alias="date")]


def _new_task(services: Container, shown: date) -> NewTaskForm | None:
    """The New task panel, prefilled with the shown day; None hides it with the item controls."""
    return None if services.items is None else NewTaskForm(due_date=shown.isoformat())


def pages_router(get_container: Callable[..., Container], renderer: Renderer) -> APIRouter:
    """Routes for the three agenda pages."""
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    async def today_page(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        day: DayParam = None,
    ) -> HTMLResponse:
        agenda = services.agenda
        shown = day or agenda.today()
        events = await agenda.day(shown)
        attention = await agenda.attention()
        marks = await page_marks(services, events, attention)
        view = today_view(events, attention, shown, agenda.tz, now=agenda.now(), marks=marks)
        card = await summary_card(services, shown, generate=False)
        context = {
            "active": "today",
            "view": view,
            "nt": _new_task(services, shown),
            **summary_context(card),
        }
        return renderer.render(request, "today.html", context)

    @router.get("/week", response_class=HTMLResponse)
    async def week_page(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        day: DayParam = None,
    ) -> HTMLResponse:
        agenda = services.agenda
        today = agenda.today()
        shown = day or today
        events = await agenda.week(shown)
        marks = await page_marks(services, events)
        view = week_view(events, shown, today, agenda.tz, now=agenda.now(), marks=marks)
        context = {"active": "week", "view": view, "nt": _new_task(services, shown)}
        return renderer.render(request, "week.html", context)

    @router.get("/month", response_class=HTMLResponse)
    async def month_page(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        day: DayParam = None,
    ) -> HTMLResponse:
        agenda = services.agenda
        today = agenda.today()
        shown = day or today
        events = await agenda.month(shown)
        marks = await page_marks(services, events)
        view = month_view(events, shown, today, agenda.tz, now=agenda.now(), marks=marks)
        context = {"active": "month", "view": view, "nt": _new_task(services, shown)}
        return renderer.render(request, "month.html", context)

    return router
