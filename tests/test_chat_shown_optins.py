"""What /chat showed is what is sent: a message that carries the opt-ins its page showed is refused
when the stored opt-ins have since changed (another tab, or a tick that landed late).

The history and notes opt-ins are stored settings shared by every tab and by the API, so a page
can go stale. A stale page that shows "off" while another tab turned history on would send more
than it discloses; the service compares the two on the same config read that builds the context.
"""

import asyncio
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient

from chat_support import FakeChatProvider, make_chat_rig
from command_center.core.chat import ChatMessage
from command_center.services.chat import ChatShown
from command_center.services.errors import ChatSettingsChangedError
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine
from web_chat_support import HEADERS, LOCAL, WebChatRig, make_web_chat_rig

CHANGED = "Settings changed in another tab; reload the page"
OFF = ChatShown(include_history=False, include_notes=False)


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


class SignallingLock(asyncio.Lock):
    """A lock that says when something had to wait for it."""

    def __init__(self) -> None:
        super().__init__()
        self.contended = asyncio.Event()

    async def acquire(self) -> Literal[True]:
        if self.locked():
            self.contended.set()
        return await super().acquire()


class HoldingProvider(FakeChatProvider):
    """Answers only when released, so a second message can queue behind the first."""

    def __init__(self) -> None:
        super().__init__("A reply")
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, messages: Sequence[ChatMessage], system: str, max_tokens: int) -> str:
        self.started.set()
        _ = await self.release.wait()
        return await super().complete(messages, system, max_tokens)


# --- the service ------------------------------------------------------------------------------


async def test_a_message_whose_page_showed_history_off_is_refused_when_it_is_on(
    ledger: LedgerRig,
) -> None:
    chat = make_chat_rig(ledger)
    await chat.settings.set_include_history(enabled=True)

    with pytest.raises(ChatSettingsChangedError) as raised:
        _ = await chat.service.reply("what did I finish?", shown=OFF)

    assert str(raised.value) == CHANGED
    assert chat.provider.calls == []


async def test_a_message_whose_page_showed_notes_off_is_refused_when_they_are_on(
    ledger: LedgerRig,
) -> None:
    chat = make_chat_rig(ledger)
    await chat.settings.set_include_notes(enabled=True)

    with pytest.raises(ChatSettingsChangedError):
        _ = await chat.service.reply("hello", shown=OFF)

    assert chat.provider.calls == []


async def test_a_page_that_showed_history_on_is_refused_when_it_is_off(ledger: LedgerRig) -> None:
    chat = make_chat_rig(ledger)

    with pytest.raises(ChatSettingsChangedError):
        _ = await chat.service.reply(
            "hello", shown=ChatShown(include_history=True, include_notes=False)
        )

    assert chat.provider.calls == []


async def test_a_page_that_showed_what_is_stored_is_answered(ledger: LedgerRig) -> None:
    chat = make_chat_rig(ledger)
    await chat.settings.set_include_history(enabled=True)

    answer = await chat.service.reply(
        "hello", shown=ChatShown(include_history=True, include_notes=False)
    )

    assert answer.reply == "A reply"
    assert "History (recent):" in chat.provider.calls[0].system


async def test_no_shown_value_keeps_the_stored_setting_meaning_for_the_api(
    ledger: LedgerRig,
) -> None:
    chat = make_chat_rig(ledger)
    await chat.settings.set_include_history(enabled=True)

    _ = await chat.service.reply("hello")

    assert "History (recent):" in chat.provider.calls[0].system


async def test_a_refused_mismatch_does_not_use_up_a_message_of_the_limit(
    ledger: LedgerRig,
) -> None:
    chat = make_chat_rig(ledger, limit=1)
    await chat.settings.set_include_history(enabled=True)
    with pytest.raises(ChatSettingsChangedError):
        _ = await chat.service.reply("first", shown=OFF)

    answer = await chat.service.reply(
        "second", shown=ChatShown(include_history=True, include_notes=False)
    )

    assert answer.reply == "A reply"


async def test_a_change_made_while_the_message_waits_for_the_lock_is_caught(
    ledger: LedgerRig,
) -> None:
    provider = HoldingProvider()
    chat = make_chat_rig(ledger, provider)
    lock = SignallingLock()
    chat.service._lock = lock  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    ledger.events.upsert([assignment("a", title="Open-item")])
    first = asyncio.create_task(chat.service.reply("first"))
    _ = await provider.started.wait()
    second = asyncio.create_task(chat.service.reply("second", shown=OFF))
    async with asyncio.timeout(5):  # only so a missing signal fails instead of hanging
        _ = await lock.contended.wait()  # the second message passed the first check and waits

    await chat.settings.set_include_history(enabled=True)  # another tab ticks it
    provider.release.set()

    _ = await first
    with pytest.raises(ChatSettingsChangedError):
        _ = await second
    assert len(provider.calls) == 1


async def test_the_connection_test_is_not_affected(ledger: LedgerRig) -> None:
    chat = make_chat_rig(ledger)
    await chat.settings.set_include_history(enabled=True)

    await chat.service.test_connection()

    assert [m.content for m in chat.provider.calls[0].messages] == ["Reply with OK."]


def test_the_shown_pair_is_a_frozen_value() -> None:
    with pytest.raises(ValueError, match="frozen"):
        OFF.include_history = True  # pyright: ignore[reportAttributeAccessIssue]


# --- the page ---------------------------------------------------------------------------------

SHOWN_HISTORY = re.compile(r'name="shown_history" value="(on|off)"')
SHOWN_NOTES = re.compile(r'name="shown_notes" value="(on|off)"')


@pytest.fixture
def rig(ledger: LedgerRig) -> WebChatRig:
    return make_web_chat_rig(ledger, FakeChatProvider("Two things are due."))


def shown(html: str) -> tuple[str, str]:
    history, notes = SHOWN_HISTORY.search(html), SHOWN_NOTES.search(html)
    assert history is not None
    assert notes is not None
    return history.group(1), notes.group(1)


def send(rig: WebChatRig, **form: str) -> Any:  # noqa: ANN401
    return rig.client.post(
        "/chat/message", data={"message": "hello", "conversation_id": "", **form}, headers=HEADERS
    )


def test_the_page_says_which_opt_ins_it_showed(rig: WebChatRig) -> None:
    assert shown(rig.page("/chat")) == ("off", "off")


def test_the_context_block_says_so_again_after_a_tick(rig: WebChatRig) -> None:
    html = rig.client.post("/chat/context", data={"include_history": "on"}, headers=HEADERS).text

    assert shown(html) == ("on", "off")


def test_the_message_form_carries_what_the_page_showed(rig: WebChatRig) -> None:
    html = rig.page("/chat")

    form = re.search(r'<form id="chat-form"[^>]*>', html)
    assert form is not None
    assert 'hx-include="#chat-context-form"' in form.group(0)
    assert 'id="chat-context-form"' in html  # the form the hidden values live in


def test_a_stale_tab_that_showed_off_cannot_send_history_another_tab_turned_on(
    rig: WebChatRig,
) -> None:
    tab_a = rig.page("/chat")  # shows both off
    rig.client.post("/chat/context", data={"include_history": "on"}, headers=HEADERS)  # tab B

    history, notes = shown(tab_a)
    response = send(rig, shown_history=history, shown_notes=notes)

    assert response.status_code == 409
    assert response.json() == {"detail": CHANGED}
    assert rig.chat.provider.calls == []


def test_a_stale_tab_that_showed_notes_on_cannot_send_after_a_reset(rig: WebChatRig) -> None:
    rig.client.post("/chat/context", data={"include_notes": "on"}, headers=HEADERS)
    tab_a = shown(
        rig.client.post("/chat/context", data={"include_notes": "on"}, headers=HEADERS).text
    )
    rig.page("/chat")  # tab B opens: both opt-ins switch off

    response = send(rig, shown_history=tab_a[0], shown_notes=tab_a[1])

    assert response.status_code == 409
    assert rig.chat.provider.calls == []


def test_a_page_that_is_current_is_answered_with_what_it_showed(rig: WebChatRig) -> None:
    html = rig.client.post("/chat/context", data={"include_history": "on"}, headers=HEADERS).text
    history, notes = shown(html)

    response = send(rig, shown_history=history, shown_notes=notes)

    assert response.status_code == 200
    assert "History (recent):" in rig.chat.provider.calls[0].system


def test_a_post_without_the_shown_values_is_the_old_behaviour(rig: WebChatRig) -> None:
    rig.client.post("/chat/context", data={"include_history": "on"}, headers=HEADERS)

    response = send(rig)

    assert response.status_code == 200
    assert "History (recent):" in rig.chat.provider.calls[0].system


def test_one_shown_value_alone_counts_the_other_as_off(rig: WebChatRig) -> None:
    rig.client.post("/chat/context", data={"include_notes": "on"}, headers=HEADERS)

    response = send(rig, shown_history="off")

    assert response.status_code == 409


def test_two_clients_tab_b_ticks_history_and_tab_a_sends_nothing(rig: WebChatRig) -> None:
    tab_a = TestClient(rig.app, base_url=LOCAL)
    tab_b = TestClient(rig.app, base_url=LOCAL)
    page_a = tab_a.get("/chat").text  # loads and resets: shows both unticked
    tab_b.post("/chat/context", data={"include_history": "on"}, headers=HEADERS)

    history, notes = shown(page_a)
    response = tab_a.post(
        "/chat/message",
        data={
            "message": "hello",
            "conversation_id": "",
            "shown_history": history,
            "shown_notes": notes,
        },
        headers=HEADERS,
    )

    assert (history, notes) == ("off", "off")
    assert response.status_code == 409
    assert response.json() == {"detail": CHANGED}
    assert rig.chat.provider.calls == []
