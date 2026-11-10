"""The settings page and its HTMX fragments: connect, status polling, actions, delete."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse

from command_center.services.container import Container
from command_center.web.cards import card_view
from command_center.web.checklist import checklist_rows
from command_center.web.loopback import require_loopback
from command_center.web.render import Renderer
from command_center.web.settings_actions import SettingsActions, find


def settings_router(get_container: Callable[..., Container], renderer: Renderer) -> APIRouter:
    """Routes for /settings. Values go in through PUT and only their status comes back out."""
    router = APIRouter()
    actions = SettingsActions(renderer)

    @router.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_loopback)])
    async def settings_page(
        request: Request, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        items = await services.settings.status()
        context = {
            "active": "settings",
            "cards": [card_view(item) for item in items],
            "checklist": checklist_rows(services.settings.checklist(items)),
        }
        return renderer.render(request, "settings.html", context)

    @router.get(
        "/settings/{source}/status",
        response_class=HTMLResponse,
        dependencies=[Depends(require_loopback)],
    )
    async def source_status(
        request: Request, source: str, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        view = card_view(await find(services, source))
        return renderer.render(request, "_status_fragment.html", {"card": view})

    @router.put("/settings/{source}", response_class=HTMLResponse)
    async def connect_source(
        request: Request,
        source: str,
        services: Annotated[Container, Depends(get_container)],
        background: BackgroundTasks,
    ) -> HTMLResponse:
        item = await find(services, source)
        return await actions.run(request, services, item, dict(await request.form()), background)

    @router.delete("/settings/{source}", response_class=HTMLResponse)
    async def delete_source(
        request: Request, source: str, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        await find(services, source)
        result = await services.settings.disconnect(source)
        if result.sync is not None:  # disconnect only leaves a state behind when it failed
            return await actions.card(request, services, source, result.sync.message, ok=False)
        return await actions.card(request, services, source, "Deleted.")

    return router
