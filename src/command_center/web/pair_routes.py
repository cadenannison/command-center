"""The pairing page: a button that makes a one-time code and shows it as a QR. Loopback only."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from markupsafe import Markup

from command_center.core.hosts import Exposure, classify_request
from command_center.core.pairing import PAIRING_TTL
from command_center.pairing.qr import pairing_payload, qr_svg
from command_center.services.container import Container
from command_center.services.pairing import PairingService
from command_center.web.render import Renderer

NOT_CONFIGURED = (
    "No tailnet name is set. Set CC_ALLOWED_HOSTS to the name Tailscale Serve answers on "
    "(for example mac.tail1234.ts.net) and restart; see docs/mobile.md."
)
_MINUTES = int(PAIRING_TTL.total_seconds() // 60)


def _loopback_only(request: Request) -> None:
    """404 unless the Host is loopback and the request carries no proxy header.

    A tailnet client must never be able to mint a pairing code, even with a valid device token:
    a stolen phone could otherwise pair more phones.
    """
    exposure = classify_request(request.headers.get("host"), request.headers.keys(), ())
    if exposure is not Exposure.LOOPBACK:
        raise HTTPException(status_code=404, detail="Not found")


def pair_router(get_container: Callable[..., Container], renderer: Renderer) -> APIRouter:
    """Routes for /pair. A code is made by POST (CSRF-checked), never by a GET."""
    router = APIRouter(dependencies=[Depends(_loopback_only)])

    def pairing_of(services: Container) -> PairingService:
        if services.pairing is None:
            raise HTTPException(status_code=404, detail="Not found")
        return services.pairing

    @router.get("/pair", response_class=HTMLResponse)
    async def pair_page(
        request: Request, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        pairing = pairing_of(services)
        context = {"active": "pair", "configured": pairing.base_url is not None}
        return renderer.render(request, "pair.html", context | {"not_configured": NOT_CONFIGURED})

    @router.post("/pair/code", response_class=HTMLResponse)
    def make_code(
        request: Request, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        pairing = pairing_of(services)
        url = pairing.base_url
        if url is None:
            return renderer.render(request, "_pair_code.html", {"error": NOT_CONFIGURED})
        offer = pairing.start_pairing()
        context = {
            "url": url,
            "token": offer.token,
            "minutes": _MINUTES,
            "svg": Markup(qr_svg(pairing_payload(url, offer.token))),  # noqa: S704 - library-drawn paths from our own payload
        }
        return renderer.render(request, "_pair_code.html", context)

    return router
