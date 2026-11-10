"""Chat settings changed while a message waits are honoured; the delete route's id and off state."""

import asyncio
import logging
import traceback
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from chat_support import ChatRig, FakeChatProvider, make_chat_rig
from command_center.api import create_app
from command_center.core.chat import ChatMessage
from command_center.services.chat import ChatReply
from command_center.services.container import Container
from command_center.services.errors import ChatDisabledError, ChatUnavailableError
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from fakes import InMemorySecretStore
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine

NOTE = "fake-note-needle"


class HoldingProvider(FakeChatProvider):
    """Answers only when released, so a second message can queue behind the first."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, messages: Sequence[ChatMessage], system: str, max_tokens: int) -> str:
        _ = await super().complete(messages, system, max_tokens)
        self.started.set()
        _ = await self.release.wait()
        return "A reply"


class SignallingLock(asyncio.Lock):
    """A lock that says out loud when a task finds it held and starts waiting for it."""

    def __init__(self) -> None:
        super().__init__()
        self.contended = asyncio.Event()

    async def acquire(self) -> Literal[True]:
        if self.locked():
            self.contended.set()
        return await super().acquire()


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


async def _queued_behind_a_held_message(
    rig_provider: HoldingProvider, ledger: LedgerRig
) -> tuple[ChatRig, "asyncio.Task[ChatReply]", "asyncio.Task[ChatReply]"]:
    chat = make_chat_rig(ledger, rig_provider)
    lock = SignallingLock()
    chat.service._lock = lock  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    ledger.events.upsert([assignment("a", title="Open-item")])
    await ledger.items.set_note("a", NOTE)
    await chat.settings.set_include_notes(enabled=True)
    first = asyncio.create_task(chat.service.reply("first"))
    _ = await rig_provider.started.wait()
    second = asyncio.create_task(chat.service.reply("second"))
    async with asyncio.timeout(5):  # only so a missing signal fails instead of hanging
        _ = await lock.contended.wait()
    return chat, first, second


async def test_a_message_queued_before_chat_is_turned_off_sends_nothing(ledger: LedgerRig) -> None:
    provider = HoldingProvider()
    chat, first, second = await _queued_behind_a_held_message(provider, ledger)

    await chat.settings.set_enabled(enabled=False)
    provider.release.set()

    assert (await first).reply == "A reply"
    with pytest.raises(ChatDisabledError):
        await second
    assert len(provider.calls) == 1


async def test_a_message_queued_before_notes_are_turned_off_carries_no_notes(
    ledger: LedgerRig,
) -> None:
    provider = HoldingProvider()
    chat, first, second = await _queued_behind_a_held_message(provider, ledger)
    assert NOTE in provider.calls[0].system

    await chat.settings.set_include_notes(enabled=False)
    provider.release.set()
    _ = await first
    _ = await second

    assert len(provider.calls) == 2
    assert NOTE not in provider.calls[1].system


def client_for(ledger: LedgerRig, *, enabled: bool) -> tuple[TestClient, str]:
    chat = make_chat_rig(ledger, enabled=True)
    secrets = InMemorySecretStore()
    sync = SyncService({}, secrets, ledger.events, ledger.clock, ledger=ledger.ledger)
    container = Container(
        sync=sync,
        agenda=ledger.agenda,
        settings=SettingsService({}, secrets, sync),
        items=ledger.items,
        chat=chat.service,
    )
    client = TestClient(create_app(container), base_url="http://localhost")
    conversation = client.post("/v1/chat", json={"message": "hi"}).json()["conversation_id"]
    if not enabled:
        asyncio.run(chat.settings.set_enabled(enabled=False))
    return client, str(conversation)


def test_a_conversation_can_be_forgotten_after_chat_is_turned_off(ledger: LedgerRig) -> None:
    client, conversation = client_for(ledger, enabled=False)

    assert client.delete(f"/v1/chat/{conversation}").status_code == 204
    assert client.delete(f"/v1/chat/{conversation}").status_code == 404


@pytest.mark.parametrize("bad", ["a" * 65, "has.dot", "semi;colon"])
def test_a_delete_with_a_malformed_id_is_422_and_echoes_nothing(
    ledger: LedgerRig, bad: str
) -> None:
    client, _ = client_for(ledger, enabled=True)

    response = client.delete(f"/v1/chat/{bad}")

    assert response.status_code == 422
    assert bad not in response.text


LEAKY_TEXT = "fake-sdk-message carrying the system prompt and the agenda-needle"


@pytest.mark.parametrize("error", [RuntimeError(LEAKY_TEXT), KeyError(LEAKY_TEXT)])
def test_an_arbitrary_provider_exception_is_a_502_and_its_text_reaches_no_response_or_log(
    ledger: LedgerRig, error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    chat = make_chat_rig(ledger, FakeChatProvider(error))
    secrets = InMemorySecretStore()
    sync = SyncService({}, secrets, ledger.events, ledger.clock, ledger=ledger.ledger)
    container = Container(
        sync=sync,
        agenda=ledger.agenda,
        settings=SettingsService({}, secrets, sync),
        items=ledger.items,
        chat=chat.service,
    )
    client = TestClient(create_app(container), base_url="http://localhost")
    caplog.set_level(logging.DEBUG)

    response = client.post("/v1/chat", json={"message": "hi"})

    assert response.status_code == 502
    assert response.json() == {
        "detail": "The chat provider failed: the request could not be completed"
    }
    assert "fake-sdk-message" not in response.text + str(dict(response.headers))
    for record in caplog.records:
        assert "fake-sdk-message" not in record.getMessage()
        assert "fake-sdk-message" not in repr(record.__dict__)
        assert record.exc_info is None
        assert record.exc_text is None
    assert any(r.__dict__.get("error_class") == type(error).__name__ for r in caplog.records)


async def test_the_unavailable_error_for_an_arbitrary_exception_carries_no_trace_of_it(
    ledger: LedgerRig,
) -> None:
    chat = make_chat_rig(ledger, FakeChatProvider(RuntimeError(LEAKY_TEXT)))

    with pytest.raises(ChatUnavailableError) as caught:
        _ = await chat.service.reply("hi")

    assert caught.value.reason == "failed"
    assert "fake-sdk-message" not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


async def test_cancelling_a_chat_turn_is_not_swallowed_by_the_catch_all(
    ledger: LedgerRig,
) -> None:
    provider = HoldingProvider()
    chat = make_chat_rig(ledger, provider)
    turn = asyncio.create_task(chat.service.reply("hi"))
    _ = await provider.started.wait()

    _ = turn.cancel()

    with pytest.raises(asyncio.CancelledError):
        _ = await turn


async def test_a_cancelled_chat_turn_releases_the_lock_for_the_next_message(
    ledger: LedgerRig,
) -> None:
    provider = HoldingProvider()
    chat = make_chat_rig(ledger, provider)
    turn = asyncio.create_task(chat.service.reply("hi"))
    _ = await provider.started.wait()
    _ = turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        _ = await turn
    provider.release.set()

    async with asyncio.timeout(5):  # a leaked lock would hang here
        reply = await chat.service.reply("again")

    assert reply.reply == "A reply"
