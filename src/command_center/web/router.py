"""The web router: agenda pages and settings, behind a per-process CSRF token."""

from fastapi import APIRouter, Depends, Request

from command_center.services.container import Container
from command_center.web.ai_settings import ai_router
from command_center.web.chat_page import chat_router
from command_center.web.csrf import new_token, require_csrf
from command_center.web.history import history_router
from command_center.web.item_routes import item_router
from command_center.web.pages import pages_router
from command_center.web.pair_routes import pair_router
from command_center.web.render import Renderer
from command_center.web.settings_routes import settings_router
from command_center.web.summary import summary_router


def create_router(
    container: Container | None = None, *, csrf_token: str | None = None
) -> APIRouter:
    """Build the web router.

    Without `container` it reads `request.app.state.container`, as the API does, so a router can
    be mounted on an app whose container is built at startup (decision 0021). `csrf_token`
    defaults to a fresh random token for this process.
    """
    token = csrf_token or new_token()

    def get_container(request: Request) -> Container:
        found: Container | None = container or getattr(request.app.state, "container", None)
        if found is None:
            msg = "The service container is not ready; the app has not started"
            raise RuntimeError(msg)
        return found

    renderer = Renderer(token)
    router = APIRouter(dependencies=[Depends(require_csrf(token))], include_in_schema=False)
    router.include_router(pages_router(get_container, renderer))
    router.include_router(settings_router(get_container, renderer))
    router.include_router(pair_router(get_container, renderer))
    router.include_router(chat_router(get_container, renderer))
    router.include_router(ai_router(get_container, renderer))
    router.include_router(summary_router(get_container, renderer))
    router.include_router(item_router(get_container, renderer))
    router.include_router(history_router(get_container, renderer))
    return router
