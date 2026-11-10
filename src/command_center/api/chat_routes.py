"""Read-only chat about the agenda: loopback only, 404 while chat is off (0160-0169)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response
from pydantic import BaseModel, Field, StringConstraints

from command_center.api.deps import ContainerDep
from command_center.api.errors import INVALID_REQUEST, NOT_FOUND, ErrorBody
from command_center.core.chat import MAX_MESSAGE_CHARS
from command_center.services.chat import ChatContextPreview, ChatReply, ChatService
from command_center.services.container import Container
from command_center.services.errors import (
    ChatConversationNotFoundError,
    ChatDisabledError,
    ChatNotConfiguredError,
    ChatRateLimitedError,
    ChatUnavailableError,
)

router = APIRouter(prefix="/v1", tags=["chat"])

CHAT_OFF = "Chat is off"
_NO_STORE = {"Cache-Control": "no-store"}
_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"  # a pattern is a search, so it is anchored

_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorBody, "description": "Chat is off, or there is no such conversation"},
    409: {"model": ErrorBody, "description": "Chat is on but its provider setting is unusable"},
    429: {
        "model": ErrorBody,
        "description": "Too many messages in the last minute; wait Retry-After seconds",
        "headers": {"Retry-After": {"schema": {"type": "integer"}}},
    },
    502: {"model": ErrorBody, "description": "The chat provider failed; the detail is redacted"},
}
# The preview never calls a provider, so it has no 429 or 502; it works while chat is off, so its
# 404 means chat is not wired into this server at all (decision 0169).
_PREVIEW_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorBody, "description": "Chat is not wired into this server"},
    409: _RESPONSES[409],
}


class ChatRequest(BaseModel):
    """One message from the user."""

    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS)
    ]
    conversation_id: Annotated[str, StringConstraints(pattern=_ID_PATTERN)] | None = Field(
        default=None,
        description="Continue this conversation; omit to start one. Ids are issued by the server.",
    )


def _service(container: Container) -> ChatService:
    if container.chat is None:
        raise HTTPException(status_code=404, detail=CHAT_OFF)
    return container.chat


@router.post(
    "/chat",
    summary="Send a message to the chat assistant",
    responses={**_RESPONSES, **INVALID_REQUEST},
)
async def post_chat(container: ContainerDep, body: ChatRequest, response: Response) -> ChatReply:
    """The assistant's `reply` and the `conversation_id` to continue with.

    The assistant is read-only: it sees a redacted, size-capped view of the next 7 days (and,
    only if the user opted in, recent history and notes), and has no tools, so nothing it says
    changes anything. Conversations are kept in memory (20 turns) and lost on restart: an unknown
    `conversation_id` is a 404. Loopback only: a paired phone gets 403. At most 10 messages a
    minute. 404 while chat is off (the default).
    """
    service = _service(container)
    response.headers.update(_NO_STORE)
    try:
        return await service.reply(body.message, body.conversation_id)
    except ChatDisabledError:
        raise HTTPException(status_code=404, detail=CHAT_OFF, headers=_NO_STORE) from None
    except ChatConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc), headers=_NO_STORE) from None
    except ChatNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc), headers=_NO_STORE) from None
    except ChatRateLimitedError as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds), **_NO_STORE},
        ) from None
    except ChatUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc), headers=_NO_STORE) from None


@router.get(
    "/chat/context-preview",
    summary="The exact context chat would send",
    responses=_PREVIEW_RESPONSES,
)
async def get_context_preview(container: ContainerDep, response: Response) -> ChatContextPreview:
    """The redacted `context` the next message would carry, and the opt-ins that shaped it.

    Nothing is sent to a provider. Loopback only: a paired phone gets 403, because the context is
    the user's agenda. Works while chat is off (`enabled` false), so the user can look before
    opting in.
    """
    service = _service(container)
    response.headers.update(_NO_STORE)
    try:
        return await service.context_preview()
    except ChatNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc), headers=_NO_STORE) from None


@router.delete(
    "/chat/{conversation_id}",
    summary="Forget a conversation",
    status_code=204,
    responses={**NOT_FOUND, **INVALID_REQUEST},
)
async def delete_chat(
    container: ContainerDep,
    conversation_id: Annotated[str, Path(pattern=_ID_PATTERN)],
) -> Response:
    """Drop the conversation from memory, also while chat is off. 404 when there is none."""
    service = _service(container)
    try:
        await service.delete(conversation_id)
    except ChatConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return Response(status_code=204)
