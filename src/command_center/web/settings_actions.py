"""What the settings routes do for one source: connect, save unverified, test, sync now.

All four are actions of the one `PUT /settings/{source}` route, chosen by a form field `action`
(decision 0102). The class holds the sources that have an action in flight, against a double submit.
"""

from collections.abc import Awaitable

from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse

from command_center.services.container import Container
from command_center.services.models import ConnectResult, SourceSettings
from command_center.web.cards import card_view
from command_center.web.city_search import CITY_ACTIONS, CitySearch
from command_center.web.render import Renderer
from command_center.web.sources import MAX_VALUE_LENGTH, form_for

NOTHING_ENTERED = "Fill in the fields to connect."
ALREADY_CONNECTING = "Already connecting; wait for it to finish."
TOO_LONG = f"A value is longer than {MAX_VALUE_LENGTH} characters; nothing was saved."
BUSY = "Another action on this source is still running; wait for it to finish."
CONNECT_FIRST = "Connect this source first: nothing is stored for it yet."
NO_SYNC = "This integration has no items to sync."
SYNC_RUNNING = "A sync is already running."
SYNC_STARTED = "Sync started. The status above updates when it ends."

ACTIONS = frozenset({"connect", "unverified", "test", "sync"}) | CITY_ACTIONS
NO_CITY_SEARCH = "This source has no city search"


def not_found(source: str) -> HTTPException:
    """The 404 for a source nothing is registered under."""
    return HTTPException(status_code=404, detail=f"Unknown source {source!r}")


async def find(services: Container, source: str) -> SourceSettings:
    """The settings status of source; 404 if it is not registered."""
    for item in await services.settings.status():
        if item.source == source:
            return item
    raise not_found(source)


def read_credentials(form: dict[str, object], source: str) -> dict[str, str]:
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


def _sync_refusal(services: Container, item: SourceSettings, *, busy: bool) -> str | None:
    """Why "Sync now" must not start a sync of item, or None when it may."""
    if item.source not in services.sync.sources():
        return NO_SYNC
    if not any(status.set for status in item.keys.values()):
        return CONNECT_FIRST
    if busy or (item.sync is not None and item.sync.status == "syncing"):
        return SYNC_RUNNING
    return None


class SettingsActions:
    """Runs the actions of the settings routes and renders their HTML answers."""

    def __init__(self, renderer: Renderer) -> None:
        self._renderer = renderer
        self._busy: set[str] = set()
        self._city = CitySearch(renderer)

    async def card(  # noqa: PLR0913
        self,
        request: Request,
        services: Container,
        source: str,
        flash: str = "",
        *,
        ok: bool = True,
        typed: dict[str, str] | None = None,
        offer_unverified: bool = False,
    ) -> HTMLResponse:
        """The source's card, with a message and (after a failed submit) the typed plain values."""
        view = card_view(
            await find(services, source),
            flash=flash,
            flash_ok=ok,
            typed=typed,
            offer_unverified=offer_unverified,
        )
        return self._renderer.render(request, "_card.html", {"card": view})

    async def run(
        self,
        request: Request,
        services: Container,
        item: SourceSettings,
        form: dict[str, object],
        background: BackgroundTasks,
    ) -> HTMLResponse:
        """Do the action the form names and answer with the HTML for it."""
        action = str(form.get("action") or "connect")
        if action not in ACTIONS:
            raise HTTPException(status_code=422, detail="Unknown action")
        if action in CITY_ACTIONS:
            if not form_for(item.source).city_search:
                raise HTTPException(status_code=422, detail=NO_CITY_SEARCH)
            return await self._city.run(request, services, item, action, form)
        if action == "test":
            return await self._test(request, services, item.source)
        if action == "sync":
            return self._sync_now(request, services, item, background)
        return await self._submit(
            request, services, item, form, background=background, action=action
        )

    async def _submit(  # noqa: PLR0913
        self,
        request: Request,
        services: Container,
        item: SourceSettings,
        form: dict[str, object],
        *,
        background: BackgroundTasks,
        action: str,
    ) -> HTMLResponse:
        source = item.source
        creds = read_credentials(form, source)
        refusal = _refusal(creds, item, busy=source in self._busy)
        if refusal is not None:
            return await self.card(request, services, source, refusal, ok=False, typed=creds)
        if action == "unverified":
            call = services.settings.save_unverified(source, creds)
        else:
            call = services.settings.connect(source, creds)
        result = await self._guarded(source, call)
        if action == "connect" and result.ok and result.sync is not None:
            background.add_task(services.sync.sync, source)  # an integration has nothing to sync
        return await self.card(
            request,
            services,
            source,
            result.message,
            ok=result.ok,
            typed=creds,
            offer_unverified=result.can_save_unverified,
        )

    async def _test(self, request: Request, services: Container, source: str) -> HTMLResponse:
        if source in self._busy:
            return self._outcome(request, source, BUSY, ok=False)
        result = await self._guarded(source, services.settings.check_connection(source))
        return self._outcome(request, source, result.message, ok=result.ok)

    def _sync_now(
        self,
        request: Request,
        services: Container,
        item: SourceSettings,
        background: BackgroundTasks,
    ) -> HTMLResponse:
        source = item.source
        refusal = _sync_refusal(services, item, busy=source in self._busy)
        if refusal is not None:
            return self._outcome(request, source, refusal, ok=False)
        state = services.sync.mark_syncing(source)
        self._busy.add(source)  # also covers distributed mode, where "syncing" is not stored
        background.add_task(self._run_sync, services, source)
        context = {
            "source": source,
            "message": SYNC_STARTED,
            "ok": True,
            "card": card_view(item.model_copy(update={"sync": state})),
            "oob": True,  # the status element replaces the one on the page
        }
        return self._renderer.render(request, "_action_result.html", context)

    async def _run_sync(self, services: Container, source: str) -> None:
        try:
            await services.sync.sync(source)
        finally:
            self._busy.discard(source)

    def _outcome(self, request: Request, source: str, message: str, *, ok: bool) -> HTMLResponse:
        context = {"source": source, "message": message, "ok": ok, "card": None}
        return self._renderer.render(request, "_action_result.html", context)

    async def _guarded(self, source: str, call: Awaitable[ConnectResult]) -> ConnectResult:
        """Run call with source marked busy, so a second action on it is refused meanwhile."""
        self._busy.add(source)
        try:
            return await call
        finally:
            self._busy.discard(source)
