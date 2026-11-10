"""Gaps the C2 review found: a phone's writes leave the stored opt-ins alone, and the AI card's
test button, run over the real chat adapters, keeps the address and key rules end to end.

The route-level cases use the real Ollama and OpenAI-compatible providers with respx at the httpx
boundary, so the address guard, the name lookup and the key-over-http rule are what answer.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chat_support import FAKE_KEY
from command_center.adapters import chat_http
from command_center.app import build_chat_provider
from command_center.services.chat import ChatService
from command_center.services.chat_settings import ChatConfig, ChatDefaults, ChatSettings
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from command_center.web import create_router
from fakes import InMemoryAppSettingStore, InMemorySecretStore
from ledger_support import LedgerRig, open_ledger_rig
from sink_support import open_engine
from web_chat_support import HEADERS, LOCAL, TAILNET, WebChatRig, make_web_chat_rig
from web_items_support import CSRF
from worker_support import SequentialIds

KEY_REFUSED = "The chat server key is not sent over plain http to this address; use https"
NOT_ALLOWED = "The chat server address is not allowed"
LAN = "http://10.1.2.3:11434"


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def rig(ledger: LedgerRig) -> WebChatRig:
    return make_web_chat_rig(ledger)


# --- a phone cannot change the opt-ins, by any route -------------------------------------------


def stored_on(rig: WebChatRig) -> None:
    rig.chat.store.set("chat.include_history", "on")
    rig.chat.store.set("chat.include_notes", "on")


def opt_ins(rig: WebChatRig) -> tuple[str | None, str | None]:
    return rig.chat.store.get("chat.include_history"), rig.chat.store.get("chat.include_notes")


def test_a_phone_cannot_open_the_page_and_the_stored_opt_ins_stay(rig: WebChatRig) -> None:
    stored_on(rig)

    response = TestClient(rig.app, base_url=TAILNET).get("/chat")

    assert response.status_code == 404
    assert opt_ins(rig) == ("on", "on")


def test_a_phone_cannot_tick_the_opt_ins(rig: WebChatRig) -> None:
    response = TestClient(rig.app, base_url=TAILNET).post(
        "/chat/context", data={"include_history": "on", "include_notes": "on"}, headers=HEADERS
    )

    assert response.status_code == 404
    assert opt_ins(rig) == (None, None)


def test_a_phone_cannot_press_new_chat_and_the_stored_opt_ins_stay(rig: WebChatRig) -> None:
    stored_on(rig)

    response = TestClient(rig.app, base_url=TAILNET).post("/chat/new", headers=HEADERS)

    assert response.status_code == 404
    assert opt_ins(rig) == ("on", "on")


def test_a_proxied_loopback_request_cannot_reset_or_tick_the_opt_ins(rig: WebChatRig) -> None:
    stored_on(rig)
    proxied = TestClient(rig.app, base_url=LOCAL, headers={"X-Forwarded-For": "100.64.0.9"})

    statuses = [
        proxied.get("/chat").status_code,
        proxied.post("/chat/new", headers=HEADERS).status_code,
        proxied.post("/chat/context", headers=HEADERS).status_code,
    ]

    assert statuses == [404, 404, 404]
    assert opt_ins(rig) == ("on", "on")


def test_a_phone_cannot_save_the_ai_card_or_turn_chat_on(rig: WebChatRig) -> None:
    response = TestClient(rig.app, base_url=TAILNET).put(
        "/ai/settings",
        data={"kind": "ollama", "base_url": LAN, "model": "m", "enabled": "on"},
        headers=HEADERS,
    )

    assert response.status_code == 404
    assert rig.chat.store.get("chat.enabled") is None
    assert rig.chat.store.get("chat.base_url") is None


# --- the AI card over the real adapters --------------------------------------------------------


class RealRig:
    """The web router over a ChatService that builds the real chat providers."""

    def __init__(self, ledger: LedgerRig) -> None:
        self.store = InMemoryAppSettingStore()
        self.secrets = InMemorySecretStore()
        settings = ChatSettings(self.store, ChatDefaults(enabled=False, kind="ollama"))

        def provider_for(config: ChatConfig) -> Any:  # noqa: ANN401
            return build_chat_provider(self.secrets, config)

        service = ChatService(
            settings, ledger.agenda, ledger.items, provider_for, ledger.clock, SequentialIds()
        )
        sync = SyncService({}, self.secrets, ledger.events, ledger.clock, ledger=ledger.ledger)
        container = Container(
            sync=sync,
            agenda=ledger.agenda,
            settings=SettingsService({}, self.secrets, sync),
            items=ledger.items,
            chat=service,
        )
        app = FastAPI()
        app.include_router(create_router(container, csrf_token=CSRF))
        self.client = TestClient(app, base_url=LOCAL)

    def test_button(self) -> str:
        response = self.client.post("/ai/test", headers=HEADERS)
        assert response.status_code == 200
        return response.text


def resolving_to(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> list[str]:
    looked_up: list[str] = []

    async def resolved(name: str) -> set[str]:
        looked_up.append(name)
        return set(addresses)

    monkeypatch.setattr(chat_http, "resolve_addresses", resolved)
    return looked_up


def chat_reply(text: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": text}})


@pytest.fixture
def real(ledger: LedgerRig) -> RealRig:
    return RealRig(ledger)


@respx.mock
def test_the_test_button_reaches_the_saved_lan_address_with_only_the_fixed_words(
    real: RealRig,
) -> None:
    route = respx.post(f"{LAN}/api/chat").mock(return_value=chat_reply("OK"))
    real.store.set("chat.kind", "ollama")
    real.store.set("chat.base_url", LAN)
    real.store.set("chat.model", "m")

    html = real.test_button()

    assert "OK: the provider answered the test." in html
    assert route.call_count == 1
    request: httpx.Request = route.calls.last.request
    sent = request.content.decode()
    assert "Reply with OK." in sent
    assert "Agenda" not in sent


@respx.mock
def test_a_stored_key_is_not_sent_over_plain_http_to_a_lan_server_by_the_test_button(
    real: RealRig,
) -> None:
    route = respx.post("http://10.1.2.3:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={})
    )
    real.secrets.set("chat", "api_key", FAKE_KEY)
    real.store.set("chat.kind", "openai_compatible")
    real.store.set("chat.base_url", "http://10.1.2.3:8080/v1")
    real.store.set("chat.model", "m")

    html = real.test_button()

    assert KEY_REFUSED in html
    assert FAKE_KEY not in html
    assert route.call_count == 0


@respx.mock
@pytest.mark.parametrize("host", ["localhost.", "app.localhost"])
def test_a_localhost_lookalike_with_a_key_is_refused_over_http_even_when_it_resolves_home(
    real: RealRig, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    _ = resolving_to(monkeypatch, "127.0.0.1")
    route = respx.post(f"http://{host}:1234/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={})
    )
    real.secrets.set("chat", "api_key", FAKE_KEY)
    real.client.put(
        "/ai/settings",
        data={
            "kind": "openai_compatible",
            "base_url": f"http://{host}:1234/v1",
            "model": "m",
        },
        headers=HEADERS,
    )

    html = real.test_button()

    assert KEY_REFUSED in html
    assert route.call_count == 0


@respx.mock
@pytest.mark.parametrize("host", ["localhost.", "app.localhost", "gpu-box"])
def test_a_local_name_that_resolves_to_the_metadata_address_is_not_called(
    real: RealRig, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    _ = resolving_to(monkeypatch, "169.254.169.254")
    route = respx.post(f"http://{host}:11434/api/chat").mock(return_value=chat_reply("OK"))
    saved = real.client.put(
        "/ai/settings",
        data={"kind": "ollama", "base_url": f"http://{host}:11434", "model": "m"},
        headers=HEADERS,
    )
    assert "Saved." in saved.text  # the literal rules accept the name; the lookup decides

    html = real.test_button()

    assert NOT_ALLOWED in html
    assert route.call_count == 0


@respx.mock
def test_an_address_stored_by_hand_that_the_guard_refuses_is_never_called(real: RealRig) -> None:
    real.store.set("chat.kind", "ollama")
    real.store.set("chat.base_url", "http://169.254.169.254")
    real.store.set("chat.model", "m")

    html = real.test_button()

    assert 'class="flash bad"' in html
    assert "The server address is not allowed" in html
    assert respx.calls.call_count == 0


@respx.mock
def test_the_provider_text_and_the_key_never_reach_the_test_line(real: RealRig) -> None:
    _ = respx.post(f"{LAN}/api/chat").mock(
        return_value=httpx.Response(500, text=f"boom {FAKE_KEY} from the server")
    )
    real.secrets.set("chat", "api_key", FAKE_KEY)
    real.store.set("chat.kind", "ollama")
    real.store.set("chat.base_url", LAN)
    real.store.set("chat.model", "m")

    html = real.test_button()

    assert 'class="flash bad"' in html
    assert "boom" not in html
    assert FAKE_KEY not in html
