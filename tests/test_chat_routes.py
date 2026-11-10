"""The chat routes over the real ledger and a fake provider (decisions 0160-0169)."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chat_support import FAKE_KEY, ChatRig, FakeChatProvider, make_chat_rig
from command_center.api import create_app
from command_center.core.errors import ChatProviderError, ChatRateLimited
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from fakes import InMemorySecretStore
from ledger_support import LedgerRig, assignment, open_ledger_rig
from sink_support import open_engine


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


def client_for(ledger: LedgerRig, chat: ChatRig | None) -> TestClient:
    secrets = InMemorySecretStore()
    sync = SyncService({}, secrets, ledger.events, ledger.clock, ledger=ledger.ledger)
    container = Container(
        sync=sync,
        agenda=ledger.agenda,
        settings=SettingsService({}, secrets, sync),
        items=ledger.items,
        chat=None if chat is None else chat.service,
    )
    return TestClient(create_app(container), base_url="http://localhost")


@pytest.fixture
def chat(ledger: LedgerRig) -> ChatRig:
    return make_chat_rig(ledger)


def test_a_container_without_chat_answers_404_everywhere(ledger: LedgerRig) -> None:
    client = client_for(ledger, None)

    assert client.post("/v1/chat", json={"message": "hi"}).status_code == 404
    assert client.get("/v1/chat/context-preview").status_code == 404
    assert client.delete("/v1/chat/abc").status_code == 404


def test_a_message_is_answered_and_not_cached(ledger: LedgerRig, chat: ChatRig) -> None:
    ledger.events.upsert([assignment("a", title="Essay draft")])

    response = client_for(ledger, chat).post("/v1/chat", json={"message": "What is due?"})

    assert response.status_code == 200
    assert response.json() == {"reply": "A reply", "conversation_id": "id-1"}
    assert response.headers["cache-control"] == "no-store"


def test_the_conversation_id_continues_the_conversation(ledger: LedgerRig, chat: ChatRig) -> None:
    client = client_for(ledger, chat)
    first = client.post("/v1/chat", json={"message": "one"}).json()

    second = client.post(
        "/v1/chat", json={"message": "two", "conversation_id": first["conversation_id"]}
    )

    assert second.json()["conversation_id"] == first["conversation_id"]
    assert [m.content for m in chat.provider.calls[1].messages] == ["one", "A reply", "two"]


def test_chat_off_is_404_and_nothing_leaves(ledger: LedgerRig) -> None:
    chat = make_chat_rig(ledger, enabled=False)

    response = client_for(ledger, chat).post("/v1/chat", json={"message": "hi"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Chat is off"}
    assert chat.built == []
    assert chat.provider.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"message": ""},
        {"message": "   "},
        {"message": "x" * 2001},
        {"message": "hi", "conversation_id": "../etc"},
        {"message": "hi", "conversation_id": "x" * 65},
        {"message": 5},
    ],
)
def test_an_invalid_request_is_422_and_sends_nothing(
    ledger: LedgerRig, chat: ChatRig, body: dict[str, object]
) -> None:
    response = client_for(ledger, chat).post("/v1/chat", json=body)

    assert response.status_code == 422
    assert "x" * 100 not in response.text  # the input is not echoed
    assert chat.provider.calls == []


def test_an_unknown_conversation_is_404(ledger: LedgerRig, chat: ChatRig) -> None:
    response = client_for(ledger, chat).post(
        "/v1/chat", json={"message": "hi", "conversation_id": "nope"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "No such conversation"}


def test_the_rate_limit_is_429_with_retry_after(ledger: LedgerRig) -> None:
    chat = make_chat_rig(ledger, limit=1)
    client = client_for(ledger, chat)
    assert client.post("/v1/chat", json={"message": "1"}).status_code == 200

    response = client.post("/v1/chat", json={"message": "2"})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert len(chat.provider.calls) == 1


def test_a_provider_failure_is_502_and_a_rate_limited_one_says_so(ledger: LedgerRig) -> None:
    provider = FakeChatProvider(ChatProviderError("Ollama is unreachable; is it running?"))
    chat = make_chat_rig(ledger, provider)
    client = client_for(ledger, chat)

    failed = client.post("/v1/chat", json={"message": "hi"})
    provider.outcome = ChatRateLimited("Gemini rate limit or quota reached")
    limited = client.post("/v1/chat", json={"message": "hi"})

    assert failed.status_code == limited.status_code == 502
    assert "unreachable" in failed.json()["detail"]
    assert "rate limited" in limited.json()["detail"]


def test_an_unusable_provider_setting_is_409(ledger: LedgerRig, chat: ChatRig) -> None:
    chat.store.set("chat.kind", "ollama")
    chat.store.set("chat.base_url", "http://169.254.169.254")

    response = client_for(ledger, chat).post("/v1/chat", json={"message": "hi"})

    assert response.status_code == 409
    assert "169.254" not in response.text
    assert chat.provider.calls == []


def test_the_preview_shows_the_redacted_context_and_the_opt_ins(
    ledger: LedgerRig, chat: ChatRig
) -> None:
    ledger.events.upsert([assignment("a", title="Essay 8015551234")])

    response = client_for(ledger, chat).get("/v1/chat/context-preview")

    body = response.json()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert (body["enabled"], body["include_history"], body["include_notes"]) == (True, False, False)
    assert "Essay [number]" in body["context"]
    assert "8015551234" not in response.text
    assert chat.provider.calls == []


def test_delete_forgets_a_conversation(ledger: LedgerRig, chat: ChatRig) -> None:
    client = client_for(ledger, chat)
    first = client.post("/v1/chat", json={"message": "hi"}).json()

    gone = client.delete(f"/v1/chat/{first['conversation_id']}")
    again = client.delete(f"/v1/chat/{first['conversation_id']}")

    assert gone.status_code == 204
    assert gone.content == b""
    assert again.status_code == 404


def test_the_provider_key_is_in_no_response_and_no_log(
    ledger: LedgerRig, caplog: pytest.LogCaptureFixture
) -> None:
    # the provider's failure text is attacker-shaped: it echoes the key, as a hostile server could
    provider = FakeChatProvider(ChatProviderError(f"Authorization: Bearer {FAKE_KEY} rejected"))
    chat = make_chat_rig(ledger, provider)
    caplog.set_level(logging.DEBUG)
    client = client_for(ledger, chat)

    responses = [
        client.post("/v1/chat", json={"message": "hi"}),
        client.get("/v1/chat/context-preview"),
        client.get("/v1/settings"),
    ]

    # The service passes the adapters' fixed text on; a key-shaped run in it is masked.
    for response in responses:
        assert FAKE_KEY not in response.text
    assert FAKE_KEY not in caplog.text


def test_chat_openapi_is_listed_for_the_three_routes(ledger: LedgerRig, chat: ChatRig) -> None:
    paths = client_for(ledger, chat).get("/openapi.json").json()["paths"]

    assert set(paths["/v1/chat"]) == {"post"}
    assert set(paths["/v1/chat/context-preview"]) == {"get"}
    assert set(paths["/v1/chat/{conversation_id}"]) == {"delete"}
