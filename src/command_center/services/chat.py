"""Read-only chat about the user's agenda. Decisions 0160-0169.

The model has no tools: the only thing it can do with its context is answer in text, and this
service never acts on a reply. The context is rebuilt from the agenda on every message (next 7
days), redacted and size-capped in core, and sits inside the system prompt's marked data block;
the conversation holds only what the user typed and what the model answered. With chat off the
provider is never built, so nothing leaves (rule 6).
"""

import asyncio
import logging
import math
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from command_center.core.chat import (
    AGENDA_DAYS,
    HISTORY_DAYS,
    MAX_MESSAGE_CHARS,
    MAX_REPLY_TOKENS,
    ChatMessage,
    build_context,
    build_system,
    cap_turns,
)
from command_center.core.errors import ChatProviderError, ChatRateLimited
from command_center.core.ledger import DONE_STATUS
from command_center.core.ports import ChatProvider, Clock, IdSource
from command_center.core.redact import trim
from command_center.core.schema import Event
from command_center.core.windows import TimeWindow, day_window
from command_center.services.agenda import AgendaService
from command_center.services.chat_settings import ChatConfig, ChatSettings
from command_center.services.errors import (
    ChatConversationNotFoundError,
    ChatDisabledError,
    ChatRateLimitedError,
    ChatUnavailableError,
    InvalidChatMessageError,
    safe_message,
)
from command_center.services.items import ItemService

if TYPE_CHECKING:
    from command_center.core.ledger import HistoryDay

MESSAGE_LIMIT = 10
MESSAGE_WINDOW = timedelta(seconds=60)
MAX_CONVERSATIONS = 20
MAX_REPLY_CHARS = 8000
_UNEXPECTED_DETAIL = "The chat provider failed: the request could not be completed"

logger = logging.getLogger(__name__)


class ChatReply(BaseModel):
    """The model's answer and the id of the conversation it belongs to."""

    model_config = ConfigDict(frozen=True)

    reply: str
    conversation_id: str


class ChatContextPreview(BaseModel):
    """What would be sent as context right now, redacted, and which opt-ins shaped it."""

    model_config = ConfigDict(frozen=True)

    enabled: bool
    include_history: bool
    include_notes: bool
    context: str


class ChatService:
    """Chat turns over a provider the composition root builds for the stored setting.

    Conversations live in memory only: at most MAX_CONVERSATIONS of them (the least recently used
    is dropped), each capped at MAX_TURNS turns. A message counts against a global limit of
    `limit` per `window` whether or not the provider answers, like the city search (0180).
    """

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        settings: ChatSettings,
        agenda: AgendaService,
        items: ItemService | None,
        provider_for: Callable[[ChatConfig], ChatProvider],
        clock: Clock,
        ids: IdSource,
        *,
        limit: int = MESSAGE_LIMIT,
        window: timedelta = MESSAGE_WINDOW,
    ) -> None:
        self._settings = settings
        self._agenda = agenda
        self._items = items
        self._provider_for = provider_for
        self._clock = clock
        self._ids = ids
        self._limit = limit
        self._window = window
        self._recent: deque[datetime] = deque()
        self._conversations: OrderedDict[str, list[ChatMessage]] = OrderedDict()
        # One user, one provider: one turn at a time keeps a conversation's order and cost small.
        self._lock = asyncio.Lock()

    async def enabled(self) -> bool:
        """Whether the user opted in to chat."""
        return await self._settings.enabled()

    async def reply(self, message: str, conversation_id: str | None = None) -> ChatReply:
        """Answer message in the conversation, starting one when conversation_id is None.

        Raises ChatDisabledError (checked first: nothing is built or sent), ChatNotConfiguredError,
        ChatRateLimitedError, ChatConversationNotFoundError for an id with no live conversation,
        and ChatUnavailableError when the provider fails (its own text is not passed on).
        """
        if not await self._settings.enabled():
            raise ChatDisabledError
        text = message.strip()
        if not text or len(text) > MAX_MESSAGE_CHARS:
            msg = f"A message must be 1 to {MAX_MESSAGE_CHARS} characters"
            raise InvalidChatMessageError(msg)
        config = await self._settings.config()
        self._admit()
        async with self._lock:
            # A message that waited for the lock honours a setting changed while it waited.
            if not await self._settings.enabled():
                raise ChatDisabledError
            config = await self._settings.config()
            if conversation_id is not None and conversation_id not in self._conversations:
                raise ChatConversationNotFoundError
            earlier = self._conversations.get(conversation_id or "", [])
            turns = cap_turns([*earlier, ChatMessage(role="user", content=text)])
            system = build_system(await self._context(config))
            answer = await self._ask(config, turns, system)
            new_id = conversation_id or self._ids.new_id()
            kept = cap_turns([*turns, ChatMessage(role="assistant", content=answer)])
            self._conversations[new_id] = kept
            self._conversations.move_to_end(new_id)
            while len(self._conversations) > MAX_CONVERSATIONS:
                _ = self._conversations.popitem(last=False)
        return ChatReply(reply=answer, conversation_id=new_id)

    async def context_preview(self) -> ChatContextPreview:
        """The exact context the next message would carry. Never calls a provider."""
        enabled = await self._settings.enabled()
        config = await self._settings.config()
        return ChatContextPreview(
            enabled=enabled,
            include_history=config.include_history,
            include_notes=config.include_notes,
            context=await self._context(config),
        )

    async def delete(self, conversation_id: str) -> None:
        """Forget a conversation; ChatConversationNotFoundError if there is none."""
        async with self._lock:
            if self._conversations.pop(conversation_id, None) is None:
                raise ChatConversationNotFoundError

    async def _ask(self, config: ChatConfig, turns: list[ChatMessage], system: str) -> str:
        provider = self._provider_for(config)
        try:
            answer = await provider.complete(turns, system, MAX_REPLY_TOKENS)
        except ChatProviderError as exc:
            reason = "rate_limited" if isinstance(exc, ChatRateLimited) else "failed"
            detail = safe_message(f"The chat provider {reason.replace('_', ' ')}: {exc}")
            # The provider's name and a reason; never the message sent, the context or the reply.
            logger.warning(
                "Chat provider %s %s",
                provider.name,
                reason,
                extra={"reason": f"chat_{reason}", "error_class": type(exc).__name__},
            )
            raise ChatUnavailableError(reason, detail) from None
        except Exception as exc:  # noqa: BLE001  (any other provider failure; see decision 0223)
            # Only the class name is logged: the exception's text may hold the system prompt.
            logger.warning(
                "Chat provider %s failed unexpectedly",
                provider.name,
                extra={"reason": "chat_failed", "error_class": type(exc).__name__},
            )
            reason = "failed"
            raise ChatUnavailableError(reason, _UNEXPECTED_DETAIL) from None
        text = trim(answer, MAX_REPLY_CHARS)
        if not text:
            logger.warning("Chat provider %s sent an empty reply", provider.name)
            reason = "failed"
            detail = "The chat provider sent an empty reply"
            raise ChatUnavailableError(reason, detail)
        return text

    async def _context(self, config: ChatConfig) -> str:
        today = self._agenda.today()
        events = await self._upcoming(today)
        notes: dict[str, str] | None = None
        history: list[HistoryDay] | None = None
        if config.include_notes and self._items is not None:
            notes = await self._items.notes([event.id for event in events if event.has_note])
        if config.include_history and self._items is not None:
            first = today - timedelta(days=HISTORY_DAYS - 1)
            history = await self._items.history(first, today)
        return build_context(events, today, notes=notes, history=history)

    async def _upcoming(self, today: date) -> list[Event]:
        tz = self._agenda.tz
        window = TimeWindow(
            start=day_window(today, tz).start,
            end=day_window(today + timedelta(days=AGENDA_DAYS - 1), tz).end,
        )
        events = await self._agenda.between(window)
        # A finished item is history, which is its own opt-in (decision 0163).
        return [_localise(event, tz) for event in events if event.status != DONE_STATUS]

    def _admit(self) -> None:
        # No await between the check and the append, so two messages cannot share the last slot.
        now = self._clock.now()
        while self._recent and now - self._recent[0] >= self._window:
            _ = self._recent.popleft()
        if len(self._recent) >= self._limit:
            wait = (self._recent[0] + self._window - now).total_seconds()
            logger.warning("chat message refused", extra={"reason": "chat_rate_limited"})
            raise ChatRateLimitedError(max(1, math.ceil(wait)))
        self._recent.append(now)


def _localise(event: Event, tz: tzinfo) -> Event:
    if event.due is None:
        return event
    return event.model_copy(update={"due": event.due.astimezone(tz)})
