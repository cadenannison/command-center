"""Chat settings changed while a message waits are honoured; the delete route's id and off state."""

import asyncio
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chat_support import ChatRig, FakeChatProvider, make_chat_rig
from command_center.api import create_app
from command_center.core.chat import ChatMessage
from command_center.services.chat import ChatReply
from command_center.services.container import Container
from command_center.services.errors import ChatDisabledError
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


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


async def _queued_behind_a_held_message(
    rig_provider: HoldingProvider, ledger: LedgerRig
) -> tuple[ChatRig, "asyncio.Task[ChatReply]", "asyncio.Task[ChatReply]"]:
    chat = make_chat_rig(ledger, rig_provider)
    ledger.events.upsert([assignment("a", title="Open-item")])
    await ledger.items.set_note("a", NOTE)
    await chat.settings.set_include_notes(enabled=True)
    first = asyncio.create_task(chat.service.reply("first"))
    _ = await rig_provider.started.wait()
    second = asyncio.create_task(chat.service.reply("second"))
    await asyncio.sleep(0)
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


@pytest.mark.parametrize("bad", ["a" * 65, "has.dot", "semi;colon"])
def test_a_delete_with_a_malformed_id_is_422_and_echoes_nothing(
    ledger: LedgerRig, bad: str
) -> None:
    client, _ = client_for(ledger, enabled=True)

    response = client.delete(f"/v1/chat/{bad}")

    assert response.status_code == 422
    assert bad not in response.text
