"""The settings page and its HTMX fragments: connect, status polling, delete."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from command_center.services.container import Container
from command_center.services.models import ConnectResult, SourceSettings
from command_center.web.cards import card_view
from command_center.web.render import Renderer
from command_center.web.sources import MAX_VALUE_LENGTH, form_for

NOTHING_ENTERED = "Fill in the fields to connect."
ALREADY_CONNECTING = "Already connecting; wait for it to finish."
TOO_LONG = f"A value is longer than {MAX_VALUE_LENGTH} characters; nothing was saved."


def _not_found(source: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Unknown source {source!r}")


async def _find(services: Container, source: str) -> SourceSettings:
    for item in await services.settings.status():
        if item.source == source:
            return item
    raise _not_found(source)


async def _connect(
    services: Container, source: str, creds: dict[str, str], connecting: set[str]
) -> ConnectResult:
    connecting.add(source)
    try:
        return await services.settings.connect(source, creds)
    finally:
        connecting.discard(source)


def _read_credentials(form: dict[str, object], source: str) -> dict[str, str]:
    """The non-blank values of the source's own fields; anything else posted is ignored."""
    creds: dict[str, str] = {}
    for field in form_for(source).fields:
        value = form.get(field.key)
        if isinstance(value, str) and value.strip():
            creds[field.key] = value.strip()
    return creds


def _refusal(creds: dict[str, str], item: SourceSettings, *, busy: bool) -> str | None:
    """Why a submission must not reach the service, or None when it may."""
    if any(len(value) > MAX_VALUE_LENGTH for value in creds.values()):
        return TOO_LONG
    if not creds and not any(status.set for status in item.keys.values()):
        return NOTHING_ENTERED
    return ALREADY_CONNECTING if busy else None


def settings_router(get_container: Callable[..., Container], renderer: Renderer) -> APIRouter:
    """Routes for /settings. Values go in through PUT and only their status comes back out."""
    router = APIRouter()
    connecting: set[str] = set()  # sources with a connect in flight, against a double submit

    async def card(
        request: Request, services: Container, source: str, flash: str = "", *, ok: bool = True
    ) -> HTMLResponse:
        view = card_view(await _find(services, source), flash=flash, flash_ok=ok)
        return renderer.render(request, "_card.html", {"card": view})

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(
        request: Request, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        cards = [card_view(item) for item in await services.settings.status()]
        return renderer.render(request, "settings.html", {"active": "settings", "cards": cards})

    @router.get("/settings/{source}/status", response_class=HTMLResponse)
    async def source_status(
        request: Request, source: str, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        view = card_view(await _find(services, source))
        return renderer.render(request, "_status_fragment.html", {"card": view})

    @router.put("/settings/{source}", response_class=HTMLResponse)
    async def connect_source(
        request: Request,
        source: str,
        services: Annotated[Container, Depends(get_container)],
        background: BackgroundTasks,
    ) -> HTMLResponse:
        item = await _find(services, source)
        creds = _read_credentials(dict(await request.form()), source)
        refusal = _refusal(creds, item, busy=source in connecting)
        if refusal is not None:
            return await card(request, services, source, refusal, ok=False)
        result = await _connect(services, source, creds, connecting)
        if result.ok:
            background.add_task(services.sync.sync, source)
        return await card(request, services, source, result.message, ok=result.ok)

    @router.delete("/settings/{source}", response_class=HTMLResponse)
    async def delete_source(
        request: Request, source: str, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        await _find(services, source)
        result = await services.settings.disconnect(source)
        if result.sync is not None:  # disconnect only leaves a state behind when it failed
            return await card(request, services, source, result.sync.message, ok=False)
        return await card(request, services, source, "Deleted.")

    return router
