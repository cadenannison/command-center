"""Shared wiring for the chat tests: a fake provider and a ChatService over the real SQL ledger."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from command_center.core.chat import ChatMessage
from command_center.core.errors import ChatProviderError
from command_center.services.chat import ChatService
from command_center.services.chat_settings import ChatConfig, ChatDefaults, ChatSettings
from fakes import InMemoryAppSettingStore
from ledger_support import LedgerRig
from worker_support import SequentialIds

FAKE_KEY = "fake-chat-key-ABCDEF0123456789"


@dataclass
class Call:
    messages: list[ChatMessage]
    system: str
    max_tokens: int


class FakeChatProvider:
    """A ChatProvider that answers with a canned reply or raises, and records every call."""

    name = "fake"

    def __init__(self, outcome: str | Exception = "A reply") -> None:
        self.outcome = outcome
        self.calls: list[Call] = []

    async def complete(self, messages: Sequence[ChatMessage], system: str, max_tokens: int) -> str:
        self.calls.append(Call(list(messages), system, max_tokens))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@dataclass
class ChatRig:
    ledger: LedgerRig
    provider: FakeChatProvider
    settings: ChatSettings
    store: InMemoryAppSettingStore
    service: ChatService
    built: list[ChatConfig] = field(default_factory=list[ChatConfig])


def make_chat_rig(
    ledger: LedgerRig,
    provider: FakeChatProvider | None = None,
    *,
    enabled: bool = True,
    defaults: ChatDefaults | None = None,
    limit: int = 10,
) -> ChatRig:
    """A service over the ledger rig; `built` records each config a provider was asked for."""
    fake = provider or FakeChatProvider()
    store = InMemoryAppSettingStore()
    settings = ChatSettings(
        store,
        defaults or ChatDefaults(enabled=enabled, kind="ollama"),
    )
    built: list[ChatConfig] = []

    def provider_for(config: ChatConfig) -> FakeChatProvider:
        built.append(config)
        return fake

    service = ChatService(
        settings,
        ledger.agenda,
        ledger.items,
        provider_for,
        ledger.clock,
        SequentialIds(),
        limit=limit,
        window=timedelta(seconds=60),
    )
    return ChatRig(
        ledger=ledger, provider=fake, settings=settings, store=store, service=service, built=built
    )


def failing(message: str) -> ChatProviderError:
    return ChatProviderError(message)
