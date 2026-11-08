"""Builds the FastAPI application around a service container."""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from command_center.api import agenda, health, settings, summary_routes, sync
from command_center.api.errors import install_error_handlers
from command_center.services.container import Container
from command_center.services.scheduler import SyncScheduler
from command_center.web import create_router

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]  # the Host header; blocks DNS-rebinding from a browser
STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


def create_app(
    container: Container | Callable[[], Container], *, sync_interval_minutes: int | None = None
) -> FastAPI:
    """Build the app. A factory is called at startup, so importing the app never touches disk.

    With `sync_interval_minutes` the lifespan also runs a `SyncScheduler` over the container's
    sync service: a sync of everything at startup, then one per interval. Without it nothing is
    scheduled, which is what tests want.
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

    app = FastAPI(title="Command Center", version="0.1.0", lifespan=lifespan)
    if isinstance(container, Container):
        app.state.container = container
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    install_error_handlers(app)
    for module in (health, agenda, settings, sync, summary_routes):
        app.include_router(module.router)
    # The summary route is always mounted and answers 404 while summaries are off (decision 0037).
    # The web pages and static files sit behind the Host check above, which is app-wide.
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(create_router())
    return app
