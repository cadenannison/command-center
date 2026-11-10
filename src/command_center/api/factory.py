"""Builds the FastAPI application around a service container."""

from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Security
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from command_center.api import (
    agenda,
    chat_routes,
    geocode_routes,
    health,
    items,
    pairing_routes,
    settings,
    summary_routes,
    sync,
)
from command_center.api.auth import bearer_scheme, install_auth
from command_center.api.errors import install_error_handlers
from command_center.services.container import Container
from command_center.services.scheduler import SyncScheduler
from command_center.web import create_router

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]  # the Host header; blocks DNS-rebinding from a browser
STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


def create_app(
    container: Container | Callable[[], Container],
    *,
    sync_interval_minutes: int | None = None,
    remote_hosts: Sequence[str] = (),
) -> FastAPI:
    """Build the app. A factory is called at startup, so importing the app never touches disk.

    With `sync_interval_minutes` the lifespan also runs a `SyncScheduler` over the container's
    sync service: a sync of everything at startup, then one per interval. Without it nothing is
    scheduled, which is what tests want.

    `remote_hosts` are the tailnet names served besides loopback; a request to one of them needs a
    device token (api/auth.py). Any other Host is refused.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        if not isinstance(container, Container):
            app.state.container = container()
        scheduler: SyncScheduler | None = None
        if sync_interval_minutes is not None:
            scheduler = SyncScheduler(app.state.container.sync, sync_interval_minutes)
            scheduler.start()
        try:
            yield
        finally:
            if scheduler is not None:
                await scheduler.stop()
            close = app.state.container.close
            if close is not None:
                await close()

    app = FastAPI(title="Command Center", version="0.1.0", lifespan=lifespan)
    if isinstance(container, Container):
        app.state.container = container
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[*ALLOWED_HOSTS, *remote_hosts])
    install_auth(app, remote_hosts=remote_hosts)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(pairing_routes.router)
    # The bearer scheme documents the token the tailnet needs; api/auth.py is what enforces it.
    secured = (
        agenda.router,
        settings.router,
        geocode_routes.router,
        chat_routes.router,
        items.router,
        sync.router,
        summary_routes.router,
        pairing_routes.devices_router,
    )
    for router in secured:
        app.include_router(router, dependencies=[Security(bearer_scheme)])
    # The summary route is always mounted and answers 404 while summaries are off (decision 0037).
    # The web pages and static files sit behind the Host check above, which is app-wide.
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(create_router())
    return app
