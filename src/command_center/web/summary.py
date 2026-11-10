"""The AI summary card on Today: its states and the routes that change or refresh it.

The web only asks for text. Opt-in lives in `SummaryControl` and the service it builds: with
summaries off there is no service, so nothing is sent (decisions 0004, 0112).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from command_center.services.container import Container
from command_center.services.errors import SummaryUnavailableError, UnknownSummaryProviderError
from command_center.services.summary import SummaryService, summary_text
from command_center.services.summary_control import PROVIDERS
from command_center.web.render import Renderer
from command_center.web.sources import GEMINI_CAVEAT

logger = logging.getLogger(__name__)

SummaryState = Literal["off", "no_key", "generating", "ready", "error"]

UNAVAILABLE = "Summary unavailable right now."
RATE_LIMITED = "Summary unavailable right now: the provider is limiting requests. Try again later."
_GEMINI = "gemini"
_API_KEY = "api_key"
_DEFAULT_PROVIDER = PROVIDERS[0]

DayParam = Annotated[date | None, Query(alias="date")]


@dataclass(frozen=True)
class SummaryCard:
    """What the card shows. `error` is a fixed message, never text from the provider."""

    state: SummaryState
    day: date
    provider: str
    can_configure: bool
    text: str | None = None
    error: str | None = None
    refresh: bool = False
    caveat: str | None = None


async def _gemini_key_missing(container: Container) -> bool:
    """True when the Gemini card is registered and holds no key; unknown counts as present."""
    for item in await container.settings.status():
        if item.source == _GEMINI:
            status = item.keys.get(_API_KEY)
            return status is None or not status.set
    return False


async def _provider_name(container: Container, service: SummaryService | None) -> str:
    control = container.summary_control
    if control is not None:
        return await control.provider()
    return service.provider_name if service is not None else _DEFAULT_PROVIDER


async def summary_card(
    container: Container, day: date, *, generate: bool, refresh: bool = False
) -> SummaryCard:
    """The card for day. With `generate` False it never calls the provider: the stored summary
    comes back as `ready`, and with none stored the card is `generating`, to be filled by the
    generate route once the page is up (decision 0116)."""
    service = await container.summary_service()
    provider = await _provider_name(container, service)
    can_configure = container.summary_control is not None
    if service is None:
        return SummaryCard("off", day, provider, can_configure, caveat=_caveat(provider))
    if provider == _GEMINI and await _gemini_key_missing(container):
        return SummaryCard("no_key", day, provider, can_configure)
    if not generate:
        stored = None if refresh else await service.cached(day)
        if stored is None:
            return SummaryCard("generating", day, provider, can_configure, refresh=refresh)
        return SummaryCard("ready", day, provider, can_configure, text=summary_text(stored))
    return await _generated(service, day, provider, can_configure=can_configure, refresh=refresh)


async def _generated(
    service: SummaryService, day: date, provider: str, *, can_configure: bool, refresh: bool
) -> SummaryCard:
    try:
        result = await service.generate(day, refresh=refresh)
    except SummaryUnavailableError as exc:
        message = RATE_LIMITED if exc.reason == "rate_limited" else UNAVAILABLE
        return SummaryCard("error", day, provider, can_configure, error=message)
    except Exception as exc:  # noqa: BLE001  a summary failure must not take the dashboard down
        logger.warning("Summary unavailable: %s", type(exc).__name__)
        return SummaryCard("error", day, provider, can_configure, error=UNAVAILABLE)
    return SummaryCard("ready", day, provider, can_configure, text=summary_text(result.summary))


def summary_context(card: SummaryCard) -> dict[str, object]:
    """The template variables the summary partial reads."""
    return {"s": card, "providers": PROVIDERS}


def _caveat(provider: str) -> str | None:
    return GEMINI_CAVEAT if provider == _GEMINI else None


def summary_router(get_container: Callable[..., Container], renderer: Renderer) -> APIRouter:
    """Routes that change the stored setting and fill the card (HTMX fragments)."""
    router = APIRouter()

    def respond(request: Request, card: SummaryCard) -> HTMLResponse:
        return renderer.render(request, "_summary.html", summary_context(card))

    @router.post("/summary/settings", response_class=HTMLResponse)
    async def change_settings(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        day: DayParam = None,
        enabled: Annotated[str | None, Form()] = None,
        provider: Annotated[str | None, Form()] = None,
    ) -> HTMLResponse:
        control = services.summary_control
        if control is None:
            raise HTTPException(status_code=404, detail="Summary settings are not available")
        if enabled is not None and enabled not in ("on", "off"):
            raise HTTPException(status_code=400, detail="enabled must be 'on' or 'off'")
        if provider is not None and provider not in PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unknown summary provider: {provider}")
        changed = provider is not None and provider != await control.provider()
        try:
            if provider is not None:
                await control.set_provider(provider)
        except UnknownSummaryProviderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        if enabled is not None:
            await control.set_enabled(enabled=enabled == "on")
        shown = day or services.agenda.today()
        card = await summary_card(services, shown, generate=False, refresh=changed)
        return respond(request, card)

    @router.post("/summary/generate", response_class=HTMLResponse)
    async def generate(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        day: DayParam = None,
        refresh: Annotated[bool, Query()] = False,  # noqa: FBT002
    ) -> HTMLResponse:
        shown = day or services.agenda.today()
        card = await summary_card(services, shown, generate=True, refresh=refresh)
        return respond(request, card)

    return router
