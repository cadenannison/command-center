"""The /chat page: loopback only, replies through htmx, errors as status codes (decision 0203)."""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chat_support import FakeChatProvider, failing
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine
from web_chat_support import HEADERS, LOCAL, TAILNET, WebChatRig, make_web_chat_rig

CONVERSATION = re.compile(r'id="chat-conversation" name="conversation_id" value="([^"]+)"')


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def rig(ledger: LedgerRig) -> WebChatRig:
    return make_web_chat_rig(ledger, FakeChatProvider("Two things are due."))


def send(rig: WebChatRig, message: str, conversation_id: str = "") -> Any:  # noqa: ANN401
    data = {"message": message, "conversation_id": conversation_id}
    return rig.client.post("/chat/message", data=data, headers=HEADERS)


def conversation_of(response: Any) -> str:  # noqa: ANN401
    match = CONVERSATION.search(response.text)
    assert match is not None, response.text
    return match.group(1)


def test_the_page_names_the_provider_and_model_in_use(rig: WebChatRig) -> None:
    rig.chat.store.set("chat.kind", "ollama")
    rig.chat.store.set("chat.base_url", "")
    rig.chat.store.set("chat.model", "fake-model-7b")

    html = rig.page("/chat")

    assert "Provider: <strong>Ollama</strong>" in html
    assert "model: <strong>fake-model-7b</strong>" in html


def test_the_page_never_shows_the_provider_address(rig: WebChatRig) -> None:
    rig.chat.store.set("chat.kind", "ollama")
    rig.chat.store.set("chat.base_url", "http://fake-llm.local:11434")
    rig.chat.store.set("chat.model", "m")

    assert "fake-llm" not in rig.page("/chat")


@pytest.mark.parametrize("path", ["/chat"])
def test_a_tailnet_host_gets_404_for_the_page(rig: WebChatRig, path: str) -> None:
    assert TestClient(rig.app, base_url=TAILNET).get(path).status_code == 404


def test_a_loopback_host_with_a_proxy_header_gets_404_for_the_page(rig: WebChatRig) -> None:
    client = TestClient(rig.app, base_url=LOCAL, headers={"X-Forwarded-For": "100.64.0.9"})

    assert client.get("/chat").status_code == 404


def test_a_tailnet_host_cannot_send_and_the_provider_is_not_called(rig: WebChatRig) -> None:
    client = TestClient(rig.app, base_url=TAILNET)

    response = client.post("/chat/message", data={"message": "hi"}, headers=HEADERS)

    assert response.status_code == 404
    assert rig.chat.provider.calls == []


def test_the_chat_link_is_drawn_for_loopback(rig: WebChatRig) -> None:
    assert '<a href="/chat"' in rig.page("/")


def test_the_chat_link_is_not_drawn_for_a_phone(rig: WebChatRig) -> None:
    html = TestClient(rig.app, base_url=TAILNET).get("/").text

    assert '<a href="/chat"' not in html


def test_the_page_is_404_when_the_process_has_no_chat_service(ledger: LedgerRig) -> None:
    rig = make_web_chat_rig(ledger, with_chat=False)

    assert rig.client.get("/chat").status_code == 404


def test_a_reply_comes_back_with_the_question_the_answer_and_a_conversation_id(
    rig: WebChatRig,
) -> None:
    response = send(rig, "What is due?")

    assert response.status_code == 200
    assert "What is due?" in response.text
    assert "Two things are due." in response.text
    assert conversation_of(response)


def test_the_reply_swaps_in_a_new_chat_button_that_deletes_that_conversation(
    rig: WebChatRig,
) -> None:
    response = send(rig, "What is due?")

    assert f'hx-delete="/v1/chat/{conversation_of(response)}"' in response.text
    assert 'id="new-chat" hx-swap-oob="true"' in response.text


def test_the_delete_request_drops_the_form_content_type_the_api_would_refuse(
    rig: WebChatRig,
) -> None:
    html = send(rig, "What is due?").text

    assert "delete event.detail.headers['Content-Type']" in html


def test_a_second_message_continues_the_conversation(rig: WebChatRig) -> None:
    first = send(rig, "What is due?")

    send(rig, "And tomorrow?", conversation_of(first))

    roles = [m.role for m in rig.chat.provider.calls[-1].messages]
    assert roles == ["user", "assistant", "user"]


def test_the_reply_is_escaped_so_a_model_cannot_inject_markup(ledger: LedgerRig) -> None:
    rig = make_web_chat_rig(ledger, FakeChatProvider("<script>alert(1)</script>"))

    html = send(rig, "<b>hi</b>").text

    assert "<script>alert(1)" not in html
    assert "<b>hi</b>" not in html
    assert "&lt;script&gt;" in html


def test_the_reply_swaps_in_an_empty_message_box(rig: WebChatRig) -> None:
    assert re.search(
        r'<textarea id="chat-message"[^>]*hx-swap-oob="true"[^>]*></textarea>',
        send(rig, "hello").text,
    )


def test_chat_off_refuses_a_message_with_fixed_text_and_calls_no_provider(
    ledger: LedgerRig,
) -> None:
    rig = make_web_chat_rig(ledger, enabled=False)

    response = send(rig, "hello")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Chat is off. Turn it on in Settings, on the AI assistant card."
    }
    assert rig.chat.provider.calls == []


def test_chat_off_shows_a_notice_and_a_disabled_send_button(ledger: LedgerRig) -> None:
    html = make_web_chat_rig(ledger, enabled=False).page("/chat")

    assert "chat is off" in html
    assert re.search(r'<button type="submit" id="chat-send" disabled>', html)


def test_a_provider_failure_is_a_502_with_redacted_text_and_no_echo(ledger: LedgerRig) -> None:
    provider = FakeChatProvider(failing("server said 555-123-4567"))
    rig = make_web_chat_rig(ledger, provider)

    response = send(rig, "fake-secret-question")

    assert response.status_code == 502
    assert "555-123-4567" not in response.text
    assert "fake-secret-question" not in response.text


def test_the_local_limit_is_a_429_with_retry_after(ledger: LedgerRig) -> None:
    rig = make_web_chat_rig(ledger, FakeChatProvider(), limit=1)
    send(rig, "one")

    response = send(rig, "two")

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1


def test_an_unknown_conversation_is_a_404_that_says_to_press_new_chat(rig: WebChatRig) -> None:
    response = send(rig, "hello", "no-such-chat")

    assert response.status_code == 404
    assert "Press New chat" in response.json()["detail"]


def test_an_empty_message_is_a_400(rig: WebChatRig) -> None:
    assert send(rig, "   ").status_code == 400


def test_a_bad_provider_setting_is_a_409_with_its_fixed_text(ledger: LedgerRig) -> None:
    rig = make_web_chat_rig(ledger)
    rig.chat.store.set("chat.kind", "openai_compatible")  # no address, no model

    response = send(rig, "hello")

    assert response.status_code == 409
    assert "needs an address and a model" in response.json()["detail"]


def test_sending_without_the_csrf_token_is_refused(rig: WebChatRig) -> None:
    response = rig.client.post("/chat/message", data={"message": "hi"})

    assert response.status_code == 403
    assert rig.chat.provider.calls == []


def test_the_disclosure_shows_the_exact_context_text(rig: WebChatRig) -> None:
    rig.chat.ledger.events.upsert([assignment("a", title="Fake essay draft", hours=5)])

    html = rig.page("/chat")

    assert "What the assistant can see" in html
    assert "Fake essay draft" in html


def test_the_disclosure_says_in_plain_words_that_email_is_never_included(
    rig: WebChatRig,
) -> None:
    assert "Never: email" in rig.page("/chat")


def test_the_page_says_the_typed_message_is_sent_exactly_as_written(rig: WebChatRig) -> None:
    html = rig.page("/chat")

    assert "What you type here is sent to the provider exactly as written." in html
    assert html.index("<textarea") < html.index("What you type here is sent")


def test_both_opt_ins_are_off_by_default(rig: WebChatRig) -> None:
    html = rig.page("/chat")

    assert 'name="include_history" value="on" checked' not in html
    assert 'name="include_notes" value="on" checked' not in html


def test_ticking_history_stores_it_and_leaves_notes_off(rig: WebChatRig) -> None:
    response = rig.client.post("/chat/context", data={"include_history": "on"}, headers=HEADERS)

    assert 'name="include_history" value="on" checked' in response.text
    assert 'name="include_notes" value="on" checked' not in response.text
    assert rig.chat.store.get("chat.include_history") == "on"
    assert rig.chat.store.get("chat.include_notes") == "off"


def test_unticking_both_stores_off(rig: WebChatRig) -> None:
    rig.client.post(
        "/chat/context", data={"include_history": "on", "include_notes": "on"}, headers=HEADERS
    )

    rig.client.post("/chat/context", headers=HEADERS)

    assert rig.chat.store.get("chat.include_history") == "off"
    assert rig.chat.store.get("chat.include_notes") == "off"


def test_the_disclosure_stays_open_after_a_tick(rig: WebChatRig) -> None:
    html = rig.client.post("/chat/context", data={"include_notes": "on"}, headers=HEADERS).text

    assert '<details class="howto" open>' in html


def test_a_ticked_history_opt_in_is_what_the_next_message_carries(rig: WebChatRig) -> None:
    rig.client.post("/chat/context", data={"include_history": "on"}, headers=HEADERS)

    send(rig, "what did I finish?")

    assert "History (recent):" in rig.chat.provider.calls[-1].system


def test_new_chat_switches_both_opt_ins_off(rig: WebChatRig) -> None:
    rig.client.post(
        "/chat/context", data={"include_history": "on", "include_notes": "on"}, headers=HEADERS
    )

    response = rig.client.post("/chat/new", headers=HEADERS)

    assert response.status_code == 200
    assert rig.chat.store.get("chat.include_history") == "off"
    assert rig.chat.store.get("chat.include_notes") == "off"
    assert 'id="chat-panel"' in response.text


def test_new_chat_returns_an_empty_transcript_and_no_conversation_id(rig: WebChatRig) -> None:
    send(rig, "hello")

    html = rig.client.post("/chat/new", headers=HEADERS).text

    assert 'id="transcript" aria-live="polite"></div>' in html
    assert 'id="chat-conversation" name="conversation_id" value=""' in html


def test_opening_the_page_switches_both_opt_ins_off(rig: WebChatRig) -> None:
    rig.client.post(
        "/chat/context", data={"include_history": "on", "include_notes": "on"}, headers=HEADERS
    )

    html = rig.page("/chat")

    assert rig.chat.store.get("chat.include_history") == "off"
    assert rig.chat.store.get("chat.include_notes") == "off"
    assert 'name="include_notes" value="on" checked' not in html
