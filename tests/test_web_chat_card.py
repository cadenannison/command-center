"""The settings card for the chat provider key: one write-only field, a how-to, no echo."""

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from builders import NOW
from command_center.adapters.chat_openai import ChatKeyIntegration
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.credential_fields import is_secret
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from command_center.web import create_router
from fake_adapter import RecordingSleep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore
from web_rig import CSRF, DENVER, LOCAL

KEY = "fake-chat-key-ABCD1234"


class ChatRig:
    """The real web router over a settings service with only the chat key integration."""

    def __init__(self) -> None:
        self.secrets = InMemorySecretStore()
        events = InMemoryEventStore()
        clock = FakeClock(NOW)
        sync = SyncService({}, self.secrets, events, clock, sleep=RecordingSleep())
        container = Container(
            sync=sync,
            agenda=AgendaService(events, clock, DENVER),
            settings=SettingsService(
                {}, self.secrets, sync, {"chat": ChatKeyIntegration()}, clock=clock
            ),
        )
        app = FastAPI()
        app.include_router(create_router(container, csrf_token=CSRF))
        self.client = TestClient(app, base_url=LOCAL)
        self.headers = {"X-CSRF-Token": CSRF}


@pytest.fixture
def rig() -> ChatRig:
    return ChatRig()


def card(html: str) -> str:
    match = re.search(r'<section class="card" id="source-chat".*?</section>', html, flags=re.DOTALL)
    assert match is not None, "no card for chat"
    return match.group(0)


def test_the_card_asks_for_one_secret_api_key_field(rig: ChatRig) -> None:
    html = card(rig.client.get("/settings").text)

    fields = re.findall(r'<(?:input|textarea) id="f-chat-([a-z_]+)"[^>]*>', html)
    assert fields == ["api_key"]
    assert is_secret("chat", "api_key")
    assert re.search(r'<input id="f-chat-api_key"[^>]*type="password"', html)
    assert "not set" in html


def test_the_card_has_no_sync_button_and_no_provider_or_model_controls(rig: ChatRig) -> None:
    html = card(rig.client.get("/settings").text)

    assert "Sync now" not in html
    assert not re.search(r'name="(provider|kind|model|base_url)"', html)


def test_the_how_to_says_hosted_providers_need_a_key_and_local_ones_do_not(rig: ChatRig) -> None:
    html = card(rig.client.get("/settings").text)

    assert "How to connect Chat provider key" in html
    assert "Hosted providers need a key" in html
    assert "Ollama" in html
    assert "need none" in html


def test_a_saved_key_is_never_echoed_only_its_last_four(rig: ChatRig) -> None:
    response = rig.client.put("/settings/chat", data={"api_key": KEY}, headers=rig.headers)
    page = rig.client.get("/settings").text

    assert response.status_code == 200
    assert rig.secrets.get("chat")["api_key"] == KEY
    for html in (response.text, card(page)):
        assert KEY not in html
        assert KEY[:-4] not in html
        assert "ends 1234" in re.sub(r"\s+", " ", html)


def test_a_blank_key_is_refused_and_stores_nothing(rig: ChatRig) -> None:
    response = rig.client.put("/settings/chat", data={"api_key": "   "}, headers=rig.headers)

    assert response.status_code == 200
    assert "api_key" not in rig.secrets.get("chat")
