"""Today, Week and Month."""

from collections.abc import Callable
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from command_center.services.container import Container
from command_center.web.render import Renderer
from command_center.web.summary import summary_card, summary_context
from command_center.web.views import month_view, today_view, week_view

DayParam = Annotated[date | None, Query(alias="date")]


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
        view = today_view(events, attention, shown, agenda.tz)
        card = await summary_card(services, shown, generate=False)
        context = {"active": "today", "view": view, **summary_context(card)}
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
        view = week_view(await agenda.week(shown), shown, today, agenda.tz)
        return renderer.render(request, "week.html", {"active": "week", "view": view})

    @router.get("/month", response_class=HTMLResponse)
    async def month_page(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        day: DayParam = None,
    ) -> HTMLResponse:
        agenda = services.agenda
        today = agenda.today()
        shown = day or today
        view = month_view(await agenda.month(shown), shown, today, agenda.tz)
        return renderer.render(request, "month.html", {"active": "month", "view": view})

    return router
