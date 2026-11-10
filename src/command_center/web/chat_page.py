"""The /chat page: ask the assistant about the agenda. Loopback only (decision 0203).

The page calls `ChatService` directly, the way the API route does, and turns its fixed-text errors
into the same status codes, so the global htmx error listener shows them in the panel's flash area
(decision 0212). Nothing is kept on the page but the conversation id and what was typed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from command_center.services.chat import ChatService, ChatShown
from command_center.services.container import Container
from command_center.services.errors import (
    ChatConversationNotFoundError,
    ChatDisabledError,
    ChatNotConfiguredError,
    ChatRateLimitedError,
    ChatSettingsChangedError,
    ChatUnavailableError,
    InvalidChatMessageError,
)
from command_center.web.loopback import require_loopback
from command_center.web.render import Renderer

CHAT_OFF = "Chat is off. Turn it on in Settings, on the AI assistant card."
CONVERSATION_GONE = "That conversation is gone (the app may have restarted). Press New chat."
PROVIDER_LABELS = {
    "gemini": "Gemini",
    "ollama": "Ollama",
    "openai_compatible": "OpenAI-compatible server",
}
_NO_STORE = {"Cache-Control": "no-store"}


@dataclass(frozen=True)
class ChatView:
    """What the panel shows: the provider and model in use, and what would be sent."""

    enabled: bool
    provider: str
    model: str
    problem: str
    include_history: bool
    include_notes: bool
    context: str
    open_context: bool = False


async def chat_view(chat: ChatService, *, open_context: bool = False) -> ChatView:
    """The panel for the stored settings. A provider setting that cannot be used is `problem`."""
    enabled = await chat.enabled()
    try:
        config = await chat.settings.config()
        preview = await chat.context_preview()
    except ChatNotConfiguredError as exc:
        return ChatView(
            enabled,
            "not set",
            "",
            str(exc),
            include_history=False,
            include_notes=False,
            context="",
            open_context=open_context,
        )
    return ChatView(
        enabled,
        PROVIDER_LABELS[config.kind],
        config.model or "provider default",
        problem="",
        include_history=preview.include_history,
        include_notes=preview.include_notes,
        context=preview.context,
        open_context=open_context,
    )


_CHAT_ERRORS = (
    ChatDisabledError,
    ChatConversationNotFoundError,
    InvalidChatMessageError,
    ChatNotConfiguredError,
    ChatRateLimitedError,
    ChatSettingsChangedError,
    ChatUnavailableError,
)


def _refusal(exc: Exception) -> HTTPException:
    """The API's status for a chat failure, with fixed text, so the error flash can show it."""
    headers = dict(_NO_STORE)
    if isinstance(exc, ChatDisabledError):
        return HTTPException(status_code=404, detail=CHAT_OFF, headers=headers)
    if isinstance(exc, ChatConversationNotFoundError):
        return HTTPException(status_code=404, detail=CONVERSATION_GONE, headers=headers)
    if isinstance(exc, InvalidChatMessageError):
        return HTTPException(status_code=400, detail=str(exc), headers=headers)
    if isinstance(exc, ChatNotConfiguredError | ChatSettingsChangedError):
        return HTTPException(status_code=409, detail=str(exc), headers=headers)
    if isinstance(exc, ChatRateLimitedError):
        headers["Retry-After"] = str(exc.retry_after_seconds)
        return HTTPException(status_code=429, detail=str(exc), headers=headers)
    return HTTPException(status_code=502, detail=str(exc), headers=headers)


async def _start_conversation(chat: ChatService) -> None:
    """Both opt-ins off: a conversation starts with nothing extra (decision 0200)."""
    await chat.settings.set_include_history(enabled=False)
    await chat.settings.set_include_notes(enabled=False)


def chat_router(get_container: Callable[..., Container], renderer: Renderer) -> APIRouter:
    """Routes for the page. Sending is a POST (CSRF-checked); the page itself is a GET."""
    router = APIRouter(dependencies=[Depends(require_loopback)])

    def chat_of(services: Container) -> ChatService:
        if services.chat is None:
            raise HTTPException(status_code=404, detail="Not found")
        return services.chat

    async def panel(
        request: Request, chat: ChatService, name: str, *, open_context: bool = False
    ) -> HTMLResponse:
        view = await chat_view(chat, open_context=open_context)
        return renderer.render(request, name, {"c": view})

    @router.get("/chat", response_class=HTMLResponse)
    async def chat_page(
        request: Request, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        chat = chat_of(services)
        # The conversation id lives only in the page, so opening the page starts a conversation.
        await _start_conversation(chat)
        view = await chat_view(chat)
        return renderer.render(request, "chat.html", {"active": "chat", "c": view})

    @router.post("/chat/message", response_class=HTMLResponse)
    async def send_message(  # noqa: PLR0913, PLR0917  (one form field each)
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        message: Annotated[str, Form()] = "",
        conversation_id: Annotated[str, Form()] = "",
        shown_history: Annotated[str | None, Form()] = None,
        shown_notes: Annotated[str | None, Form()] = None,
    ) -> HTMLResponse:
        chat = chat_of(services)
        # A page that says what it showed is held to it; a post with neither value (an old page, a
        # script) keeps the stored-setting behaviour. One value alone counts the other as off.
        shown = None
        if shown_history is not None or shown_notes is not None:
            shown = ChatShown(
                include_history=shown_history == "on", include_notes=shown_notes == "on"
            )
        try:
            answer = await chat.reply(message, conversation_id.strip() or None, shown=shown)
        except _CHAT_ERRORS as exc:
            raise _refusal(exc) from None
        context = {"message": message.strip(), "reply": answer.reply, "id": answer.conversation_id}
        return renderer.render(request, "_chat_turn.html", context)

    @router.post("/chat/context", response_class=HTMLResponse)
    async def set_context(
        request: Request,
        services: Annotated[Container, Depends(get_container)],
        include_history: Annotated[str | None, Form()] = None,
        include_notes: Annotated[str | None, Form()] = None,
    ) -> HTMLResponse:
        chat = chat_of(services)
        await chat.settings.set_include_history(enabled=include_history == "on")
        await chat.settings.set_include_notes(enabled=include_notes == "on")
        return await panel(request, chat, "_chat_context.html", open_context=True)

    @router.post("/chat/new", response_class=HTMLResponse)
    async def new_chat(
        request: Request, services: Annotated[Container, Depends(get_container)]
    ) -> HTMLResponse:
        chat = chat_of(services)
        await _start_conversation(chat)
        return await panel(request, chat, "_chat_panel.html")

    return router
