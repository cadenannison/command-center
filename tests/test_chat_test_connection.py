"""ChatService.test_connection: one fixed prompt, no user data, also while chat is off (0201)."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from chat_support import ChatRig, FakeChatProvider, failing, make_chat_rig
from command_center.core.chat import CONTEXT_START
from command_center.services.chat import TEST_PROMPT
from command_center.services.errors import (
    ChatConversationNotFoundError,
    ChatNotConfiguredError,
    ChatRateLimitedError,
    ChatUnavailableError,
)
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def chat(ledger: LedgerRig) -> ChatRig:
    return make_chat_rig(ledger)


async def test_the_test_sends_one_fixed_prompt_and_none_of_the_agenda(chat: ChatRig) -> None:
    chat.ledger.events.upsert([assignment("a", title="Fake-private-essay")])

    await chat.service.test_connection()

    (call,) = chat.provider.calls
    assert [m.content for m in call.messages] == [TEST_PROMPT]
    assert CONTEXT_START not in call.system
    assert "Fake-private-essay" not in call.system


async def test_the_test_works_while_chat_is_off(ledger: LedgerRig) -> None:
    chat = make_chat_rig(ledger, enabled=False)

    await chat.service.test_connection()

    assert len(chat.provider.calls) == 1


async def test_the_test_keeps_no_conversation(chat: ChatRig) -> None:
    await chat.service.test_connection()

    with pytest.raises(ChatConversationNotFoundError):
        await chat.service.delete("1")


async def test_a_provider_failure_is_a_redacted_unavailable_error(ledger: LedgerRig) -> None:
    chat = make_chat_rig(ledger, FakeChatProvider(failing("down 555-123-4567")))

    with pytest.raises(ChatUnavailableError) as raised:
        await chat.service.test_connection()

    assert "555-123-4567" not in str(raised.value)


async def test_an_unusable_provider_setting_is_not_configured_and_calls_nothing(
    chat: ChatRig,
) -> None:
    chat.store.set("chat.kind", "openai_compatible")

    with pytest.raises(ChatNotConfiguredError):
        await chat.service.test_connection()

    assert chat.provider.calls == []


async def test_the_test_counts_against_the_message_limit(ledger: LedgerRig) -> None:
    chat = make_chat_rig(ledger, limit=1)
    await chat.service.test_connection()

    with pytest.raises(ChatRateLimitedError):
        await chat.service.test_connection()


async def test_the_service_exposes_its_settings(chat: ChatRig) -> None:
    assert chat.service.settings is chat.settings
