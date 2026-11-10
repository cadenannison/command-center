"""One overall deadline on every provider call, so a server that trickles bytes cannot hold the
chat lock for good (the adapters' own timeout is per read, not for the whole call).

The tests set the deadline to 0 so it fires at the provider's first wait: no real time passes.
"""

import asyncio
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chat_support import FakeChatProvider, make_chat_rig
from command_center.adapters.chat_http import TIMEOUT_SECONDS
from command_center.core.chat import ChatMessage
from command_center.services import chat as chat_module
from command_center.services.errors import ChatConversationNotFoundError, ChatUnavailableError
from ledger_support import LedgerRig, open_ledger_rig
from sink_support import open_engine
from web_chat_support import HEADERS, make_web_chat_rig

TOO_SLOW = "The chat provider did not answer in time"


class NeverAnswers(FakeChatProvider):
    """A provider that waits for ever, as a server that keeps the connection open would."""

    def __init__(self) -> None:
        super().__init__("never sent")
        self.hang = True

    async def complete(self, messages: Sequence[ChatMessage], system: str, max_tokens: int) -> str:
        if self.hang:
            _ = await asyncio.Event().wait()
        return await super().complete(messages, system, max_tokens)


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def deadline_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_module, "CALL_TIMEOUT_SECONDS", 0)


def test_the_deadline_is_two_minutes_and_not_shorter_than_the_adapters_read_timeout() -> None:
    assert chat_module.CALL_TIMEOUT_SECONDS == 120
    assert chat_module.CALL_TIMEOUT_SECONDS >= TIMEOUT_SECONDS


@pytest.mark.usefixtures("deadline_now")
async def test_a_provider_that_never_answers_ends_with_fixed_text(ledger: LedgerRig) -> None:
    chat = make_chat_rig(ledger, NeverAnswers())

    with pytest.raises(ChatUnavailableError) as raised:
        _ = await chat.service.reply("hello")

    assert str(raised.value) == TOO_SLOW
    assert raised.value.reason == "failed"


@pytest.mark.usefixtures("deadline_now")
async def test_the_lock_is_free_after_a_timed_out_message(
    ledger: LedgerRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = NeverAnswers()
    chat = make_chat_rig(ledger, provider)
    with pytest.raises(ChatUnavailableError):
        _ = await chat.service.reply("first")

    provider.hang = False
    monkeypatch.setattr(chat_module, "CALL_TIMEOUT_SECONDS", 120)
    answer = await asyncio.wait_for(chat.service.reply("second"), timeout=5)

    assert answer.reply == "never sent"


@pytest.mark.usefixtures("deadline_now")
async def test_a_timed_out_message_keeps_no_conversation(
    ledger: LedgerRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat = make_chat_rig(ledger, NeverAnswers())
    with pytest.raises(ChatUnavailableError):
        _ = await chat.service.reply("first")
    monkeypatch.setattr(chat_module, "CALL_TIMEOUT_SECONDS", 120)  # the lookup is under it too

    with pytest.raises(ChatConversationNotFoundError):
        _ = await chat.service.reply("again", "no-such-chat")


@pytest.mark.usefixtures("deadline_now")
async def test_the_connection_test_has_the_same_deadline_and_frees_the_lock(
    ledger: LedgerRig,
) -> None:
    provider = NeverAnswers()
    chat = make_chat_rig(ledger, provider)

    with pytest.raises(ChatUnavailableError) as raised:
        await chat.service.test_connection()

    assert str(raised.value) == TOO_SLOW
    assert not chat.service._lock.locked()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


@pytest.mark.usefixtures("deadline_now")
def test_the_page_shows_the_timeout_as_a_502_with_the_fixed_text(ledger: LedgerRig) -> None:
    rig = make_web_chat_rig(ledger, NeverAnswers())

    response = rig.client.post(
        "/chat/message", data={"message": "hello", "conversation_id": ""}, headers=HEADERS
    )

    assert response.status_code == 502
    assert response.json() == {"detail": TOO_SLOW}


@pytest.mark.usefixtures("deadline_now")
def test_the_test_button_shows_the_timeout_as_an_error_line(ledger: LedgerRig) -> None:
    rig = make_web_chat_rig(ledger, NeverAnswers())
    client: TestClient = rig.client
    client.put(
        "/ai/settings",
        data={"kind": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        headers=HEADERS,
    )

    html = client.post("/ai/test", headers=HEADERS).text

    assert 'class="flash bad"' in html
    assert TOO_SLOW in html


def test_the_pages_wait_a_little_longer_than_the_deadline(ledger: LedgerRig) -> None:
    """So the server's fixed error arrives before the browser gives up (no flash on a timeout)."""
    rig = make_web_chat_rig(ledger)
    chat_page = rig.page("/chat")
    ai_card = rig.page("/settings")

    for html in (chat_page, ai_card):
        assert '"timeout": 135000' in html


class Trickles(FakeChatProvider):
    """A provider that keeps sending a little, so no per-read timeout would ever fire."""

    def __init__(self) -> None:
        super().__init__("never sent")
        self.hang = True

    async def complete(self, messages: Sequence[ChatMessage], system: str, max_tokens: int) -> str:
        while self.hang:  # noqa: ASYNC110  (a server that sends a little, again and again)
            await asyncio.sleep(0)
        return await super().complete(messages, system, max_tokens)


async def test_a_provider_that_trickles_is_cut_off_and_the_next_call_works(
    ledger: LedgerRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Trickles()
    chat = make_chat_rig(ledger, provider)
    monkeypatch.setattr(chat_module, "CALL_TIMEOUT_SECONDS", 0.05)  # the loop's clock, a blink

    with pytest.raises(ChatUnavailableError) as raised:
        _ = await chat.service.reply("first")

    provider.hang = False
    answer = await asyncio.wait_for(chat.service.reply("second"), timeout=5)
    assert str(raised.value) == TOO_SLOW
    assert answer.reply == "never sent"


@pytest.mark.usefixtures("deadline_now")
async def test_waiting_for_the_lock_counts_against_the_same_deadline(ledger: LedgerRig) -> None:
    """A message queued behind a long call gives up after one deadline in total, never two."""
    chat = make_chat_rig(ledger, NeverAnswers())
    lock = chat.service._lock  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    await lock.acquire()  # the long call ahead of it

    with pytest.raises(ChatUnavailableError) as raised:
        async with asyncio.timeout(5):  # only so a missing deadline fails instead of hanging
            _ = await chat.service.reply("queued")

    assert str(raised.value) == TOO_SLOW
    assert chat.provider.calls == []
    assert lock.locked()  # still the first call's; the waiter did not take or free it
