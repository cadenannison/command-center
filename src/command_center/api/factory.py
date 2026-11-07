"""Builds the FastAPI application around a service container."""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from command_center.api import agenda, health, settings, sync
from command_center.api.errors import install_error_handlers
from command_center.services.container import Container

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]  # the Host header; blocks DNS-rebinding from a browser


def create_app(container: Container | Callable[[], Container]) -> FastAPI:
    """Build the app. A factory is called at startup, so importing the app never touches disk."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        if not isinstance(container, Container):
            app.state.container = container()
        yield

    app = FastAPI(title="Command Center", version="0.1.0", lifespan=lifespan)
    if isinstance(container, Container):
        app.state.container = container
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    install_error_handlers(app)
    for module in (health, agenda, settings, sync):
        app.include_router(module.router)
    return app
