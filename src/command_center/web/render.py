"""Template rendering shared by the page and settings routes."""

from collections.abc import Mapping
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from command_center.web.cards import POLL_SECONDS
from command_center.web.loopback import is_loopback

_NO_STORE = {"Cache-Control": "no-store"}


class Renderer:
    """Renders templates with `csrf_token` and `loopback` in every context and `no-store` set."""

    def __init__(self, csrf_token: str) -> None:
        self._csrf_token = csrf_token
        self._templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

    def render(self, request: Request, name: str, context: Mapping[str, object]) -> HTMLResponse:
        """Render template `name` as an HTML response."""
        page = {
            "csrf_token": self._csrf_token,
            "poll_seconds": POLL_SECONDS,
            "loopback": is_loopback(request),
            **context,
        }
        return self._templates.TemplateResponse(request, name, page, headers=_NO_STORE)
