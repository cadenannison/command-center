"""The AI settings card on /settings: provider, server address, model, the on switch, a test.

Everything here is non-secret and lives in the app-setting store through `ChatSettings` (decision
0161). The provider's key is not on this card: it stays on the write-only "Chat provider key" card.
Routes are loopback only; a phone never sees the page or these values (decisions 0211, 0203).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from command_center.core.chat import (
    CHAT_KINDS,
    address_holds_api_key,
    model_name_looks_like_api_key,
)
from command_center.core.urlcheck import require_chat_base_url
from command_center.services.chat import ChatService
from command_center.services.chat_settings import MAX_MODEL_LENGTH, MAX_URL_LENGTH
from command_center.services.container import Container
from command_center.services.errors import (
    ChatNotConfiguredError,
    ChatRateLimitedError,
    ChatUnavailableError,
    InvalidChatSettingError,
)
from command_center.web.howto import AI_HOWTOS, HowTo
from command_center.web.loopback import require_loopback
from command_center.web.render import Renderer
from command_center.web.sources import MAX_VALUE_LENGTH

KIND_LABELS = {
    "gemini": "Gemini (Google)",
    "ollama": "Ollama",
    "openai_compatible": "OpenAI-compatible server (LM Studio, llama.cpp, vLLM, OpenRouter)",
}
TEST_OK = "OK: the provider answered the test."
TOO_LONG = f"A value is longer than {MAX_VALUE_LENGTH} characters; nothing was saved."
UNKNOWN_KIND = "Unknown chat provider: choose gemini, ollama or openai_compatible"
_ON = "on"


@dataclass(frozen=True)
class AiCardView:
    """What the card shows. The values are the stored (or just typed) non-secret settings."""

    enabled: bool
    kind: str
    base_url: str
    model: str
    flash: str = ""
    flash_ok: bool = True
    kinds: tuple[tuple[str, str], ...] = tuple((kind, KIND_LABELS[kind]) for kind in CHAT_KINDS)
    howtos: tuple[tuple[str, HowTo], ...] = AI_HOWTOS


async def ai_card(
    chat: ChatService, *, typed: dict[str, str] | None = None, flash: str = "", ok: bool = True
) -> AiCardView:
    """The card for the stored settings; `typed` (a failed save) shows what the user entered."""
    enabled = await chat.settings.enabled()
    kind, base_url, model = CHAT_KINDS[0], "", ""
    try:
        config = await chat.settings.config()
    except ChatNotConfiguredError as exc:
        # A bad environment default: show a blank form and what is wrong with it.
        if not flash:
            flash, ok = str(exc), False
    else:
        kind, base_url, model = config.kind, config.base_url or "", config.model or ""
    if typed is not None:
        kind = typed.get("kind", kind)
        base_url = typed.get("base_url", base_url)
        model = typed.get("model", model)
        enabled = typed.get("enabled") == _ON
    return AiCardView(enabled, kind, base_url, model, flash=flash, flash_ok=ok)


def ai_router(get_container: Callable[..., Container], renderer: Renderer) -> APIRouter:
    """Routes for the card: save the settings, and test the saved ones with a fixed prompt."""
    router = APIRouter(dependencies=[Depends(require_loopback)])

    def chat_of(services: Container) -> ChatService:
        if services.chat is None:
            raise HTTPException(status_code=404, detail="Not found")
        return services.chat

    def card_response(request: Request, view: AiCardView) -> HTMLResponse:
        return renderer.render(request, "_ai_card.html", {"ai": view})

    @router.put("/ai/settings", response_class=HTMLResponse)
    async def save_settings(
        request: Request, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        chat = chat_of(services)
        form = await request.form()
        typed = {key: _text(form.get(key)) for key in ("kind", "base_url", "model", "enabled")}
        refusal = _refusal(typed)
        if refusal is None:
            try:
                await chat.settings.set_provider(
                    typed.get("kind", ""), typed.get("base_url"), typed.get("model")
                )
            except InvalidChatSettingError as exc:
                refusal = str(exc)
        if refusal is not None:
            typed["base_url"] = _shown_address(typed["base_url"])
            typed["model"] = _shown_model(typed["model"])
            return card_response(request, await ai_card(chat, typed=typed, flash=refusal, ok=False))
        await chat.settings.set_enabled(enabled=typed.get("enabled") == _ON)
        saved = "Saved. Chat is on." if typed.get("enabled") == _ON else "Saved. Chat is off."
        return card_response(request, await ai_card(chat, flash=saved))

    @router.post("/ai/test", response_class=HTMLResponse)
    async def test_connection(
        request: Request, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        chat = chat_of(services)
        message, ok = TEST_OK, True
        try:
            await chat.test_connection()
        except (ChatNotConfiguredError, ChatRateLimitedError, ChatUnavailableError) as exc:
            message, ok = str(exc), False
        context = {"source": "ai", "message": message, "ok": ok}
        return renderer.render(request, "_action_result.html", context)

    return router


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _shown_address(address: str) -> str:
    """The address to put back in the form after a refusal, or "" when it must not be echoed.

    Only a plain http(s) address with a host, no user, password, query or fragment, no key-shaped
    part and a sane length comes back; anything else may hold a pasted key (decision 0161).
    """
    if len(address) > MAX_URL_LENGTH:
        return ""
    try:
        parts = urlsplit(address)
        carries_secret = bool(parts.username or parts.password or parts.query or parts.fragment)
        usable = parts.scheme in ("http", "https") and bool(parts.hostname)
        _ = parts.port  # a key typed where the port goes raises ValueError
    except ValueError:
        return ""
    if carries_secret or not usable:
        return ""
    return "" if address_holds_api_key(address) else address


def _shown_model(model: str) -> str:
    """The model name to put back after a refusal: none when it is long or shaped like a key."""
    if len(model) > MAX_MODEL_LENGTH or model_name_looks_like_api_key(model):
        return ""
    return model


def _refusal(typed: dict[str, str]) -> str | None:
    """Why the form must not be saved, as fixed text, or None. The address is checked here with
    the same guard the adapters use, so the user sees which rule it broke (decision 0202)."""
    if any(len(value) > MAX_VALUE_LENGTH for value in typed.values()):
        return TOO_LONG
    kind = typed.get("kind", "")
    if kind not in CHAT_KINDS:
        return UNKNOWN_KIND
    address = typed.get("base_url", "")
    if kind != "gemini" and address:
        try:
            _ = require_chat_base_url(address)
        except ValueError as exc:
            return str(exc)
    return None
