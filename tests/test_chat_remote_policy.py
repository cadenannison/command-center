"""A paired phone may not use chat or read what chat would send (decision 0165).

Concrete requests, so this holds without the route table in test_remote_policy.py: the three
chat routes are refused for a phone before the handler runs, while the Mac's own browser can use
them, and nothing is sent to a provider by a refused request.
"""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auth_rig import BASE_URL, REMOTE, AuthRig, make_auth_rig
from chat_support import ChatRig, make_chat_rig
from command_center.api import create_app
from command_center.api.policy import REMOTE_DENIED_READS, remote_may_call
from ledger_support import assignment, open_ledger_rig
from sink_support import open_engine

CHAT_ROUTES = [
    ("POST", "/v1/chat", {"message": "hi"}),
    ("GET", "/v1/chat/context-preview", None),
    ("DELETE", "/v1/chat/id-1", None),
]


@pytest.fixture
def chat(tmp_path: Path) -> Iterator[ChatRig]:
    for engine in open_engine("sqlite", tmp_path):
        ledger = open_ledger_rig(engine)
        ledger.events.upsert([assignment("a", title="Agenda-title-needle")])
        yield make_chat_rig(ledger)


@pytest.fixture
def rig(chat: ChatRig) -> AuthRig:
    base = make_auth_rig()
    container = replace(base.container, chat=chat.service)
    app = create_app(container, remote_hosts=(REMOTE,))
    return replace(
        base,
        app=app,
        container=container,
        local=TestClient(app, base_url="http://localhost"),
        remote=TestClient(app, base_url=BASE_URL),
    )


@pytest.mark.parametrize(("method", "path", "body"), CHAT_ROUTES)
def test_a_phone_is_refused_every_chat_route_and_nothing_is_sent(
    rig: AuthRig, chat: ChatRig, method: str, path: str, body: dict[str, str] | None
) -> None:
    phone = rig.pair_phone()

    response = rig.remote.request(method, path, json=body, headers=rig.bearer(phone.access_token))

    assert response.status_code == 403
    assert response.json() == {"detail": "A paired phone may not do this"}
    assert "Agenda-title-needle" not in response.text
    assert chat.provider.calls == []
    assert chat.built == []


def test_the_mac_itself_may_use_chat_and_gets_the_reply_and_a_conversation(
    rig: AuthRig, chat: ChatRig
) -> None:
    response = rig.local.post("/v1/chat", json={"message": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "A reply"
    assert isinstance(body["conversation_id"], str)
    assert body["conversation_id"] != ""
    assert len(chat.provider.calls) == 1


def test_the_mac_itself_may_read_the_preview(rig: AuthRig) -> None:
    response = rig.local.get("/v1/chat/context-preview")

    assert response.status_code == 200
    assert "Agenda-title-needle" in response.json()["context"]


def test_the_policy_function_denies_the_preview_and_every_chat_write() -> None:
    assert "/v1/chat/context-preview" in REMOTE_DENIED_READS
    assert remote_may_call("GET", "/v1/chat/context-preview") is False
    assert remote_may_call("POST", "/v1/chat") is False
    assert remote_may_call("DELETE", "/v1/chat/abc") is False
