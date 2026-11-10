"""The AI settings card on /settings: provider, address, model, on switch, test (decision 0202)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chat_support import FakeChatProvider, failing
from ledger_support import LedgerRig, open_ledger_rig
from sink_support import open_engine
from web_chat_support import HEADERS, TAILNET, WebChatRig, ai_card, make_web_chat_rig

OLLAMA = {"kind": "ollama", "base_url": "http://localhost:11434", "model": "fake-model-1"}


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def rig(ledger: LedgerRig) -> WebChatRig:
    return make_web_chat_rig(ledger, FakeChatProvider("OK"), enabled=False)


def save(rig: WebChatRig, **fields: str) -> str:
    response = rig.client.put("/ai/settings", data=fields, headers=HEADERS)
    assert response.status_code == 200
    return ai_card(response.text)


def test_the_card_offers_the_three_providers(rig: WebChatRig) -> None:
    html = ai_card(rig.page("/settings"))

    for value in ("gemini", "ollama", "openai_compatible"):
        assert f'<option value="{value}"' in html


def test_the_card_has_a_how_to_for_each_provider(rig: WebChatRig) -> None:
    html = ai_card(rig.page("/settings"))

    assert "How to use Ollama" in html
    assert "How to use LM Studio or llama.cpp" in html
    assert "How to use Gemini" in html


def test_the_card_has_no_key_field_and_points_to_the_key_card(rig: WebChatRig) -> None:
    html = ai_card(rig.page("/settings"))

    assert 'type="password"' not in html
    assert 'href="#source-chat"' in html


def test_the_card_is_absent_when_the_process_has_no_chat_service(ledger: LedgerRig) -> None:
    html = make_web_chat_rig(ledger, with_chat=False).page("/settings")

    assert 'id="ai-card"' not in html


def test_chat_starts_off_on_the_card(rig: WebChatRig) -> None:
    html = ai_card(rig.page("/settings"))

    assert "Off</div>" in html
    assert 'name="enabled" value="on" checked' not in html


def test_saving_stores_the_provider_address_and_model(rig: WebChatRig) -> None:
    save(rig, **OLLAMA)

    assert rig.chat.store.get("chat.kind") == "ollama"
    assert rig.chat.store.get("chat.base_url") == "http://localhost:11434"
    assert rig.chat.store.get("chat.model") == "fake-model-1"


def test_saving_shows_the_stored_values_back(rig: WebChatRig) -> None:
    save(rig, **OLLAMA)

    html = ai_card(rig.page("/settings"))

    assert 'value="http://localhost:11434"' in html
    assert 'value="fake-model-1"' in html
    assert '<option value="ollama" selected>' in html


def test_the_on_checkbox_turns_chat_on_and_off(rig: WebChatRig) -> None:
    on = save(rig, **OLLAMA, enabled="on")
    off = save(rig, **OLLAMA)

    assert "Saved. Chat is on." in on
    assert "Saved. Chat is off." in off
    assert rig.chat.store.get("chat.enabled") == "off"


def test_a_refused_address_shows_the_fixed_reason_and_stores_nothing(rig: WebChatRig) -> None:
    html = save(rig, kind="openai_compatible", base_url="http://fake-host.example/v1", model="m")

    assert "Rejected URL: host is a private" not in html
    assert "Rejected URL" in html
    assert rig.chat.store.get("chat.kind") is None


def test_an_address_with_credentials_is_refused_without_echoing_it(rig: WebChatRig) -> None:
    html = save(rig, kind="ollama", base_url="http://user:fake-pass-123@localhost:11434", model="m")

    assert "must not embed credentials" in html
    assert "fake-pass-123" not in html


def test_the_metadata_address_is_refused(rig: WebChatRig) -> None:
    html = save(rig, kind="ollama", base_url="http://169.254.169.254", model="m")

    assert "Rejected URL" in html
    assert rig.chat.store.get("chat.base_url") is None


def test_typed_values_survive_a_failed_save(rig: WebChatRig) -> None:
    html = save(rig, kind="ollama", base_url="http://user:x@localhost:1", model="fake-keep-me")

    assert 'value="fake-keep-me"' in html
    assert '<option value="ollama" selected>' in html


def test_the_on_checkbox_survives_a_failed_save_and_chat_stays_off(rig: WebChatRig) -> None:
    html = save(rig, kind="ollama", base_url="http://169.254.169.254", model="m", enabled="on")

    assert 'name="enabled" value="on" checked' in html
    assert rig.chat.store.get("chat.enabled") is None


def test_gemini_with_an_address_is_refused_with_fixed_text(rig: WebChatRig) -> None:
    html = save(rig, kind="gemini", base_url="http://localhost:1", model="")

    assert "Gemini takes no server address" in html


def test_an_unknown_provider_is_refused(rig: WebChatRig) -> None:
    assert "Unknown chat provider" in save(rig, kind="skynet", base_url="", model="")


def test_an_openai_compatible_server_needs_an_address_and_a_model(rig: WebChatRig) -> None:
    assert "needs an address and a model" in save(rig, kind="openai_compatible")


def test_a_failed_save_is_flagged_as_an_error(rig: WebChatRig) -> None:
    assert 'class="flash bad" id="result-ai"' in save(rig, kind="skynet")


def test_test_connection_reports_ok_when_the_provider_answers(rig: WebChatRig) -> None:
    save(rig, **OLLAMA)

    response = rig.client.post("/ai/test", headers=HEADERS)

    assert response.status_code == 200
    assert "OK: the provider answered the test." in response.text
    assert 'id="result-ai"' in response.text


def test_test_connection_sends_only_the_fixed_prompt(rig: WebChatRig) -> None:
    save(rig, **OLLAMA)

    rig.client.post("/ai/test", headers=HEADERS)

    (call,) = rig.chat.provider.calls
    assert [m.content for m in call.messages] == ["Reply with OK."]
    assert "CONTEXT" not in call.system


def test_test_connection_works_while_chat_is_off(rig: WebChatRig) -> None:
    save(rig, **OLLAMA)

    assert "OK:" in rig.client.post("/ai/test", headers=HEADERS).text


def test_test_connection_reports_a_failure_as_redacted_fixed_text(ledger: LedgerRig) -> None:
    rig = make_web_chat_rig(ledger, FakeChatProvider(failing("refused 555-123-4567")))
    save(rig, **OLLAMA)

    html = rig.client.post("/ai/test", headers=HEADERS).text

    assert 'class="flash bad"' in html
    assert "The chat provider failed" in html
    assert "555-123-4567" not in html


def test_test_connection_reports_an_unusable_saved_setting(rig: WebChatRig) -> None:
    rig.chat.store.set("chat.kind", "openai_compatible")

    html = rig.client.post("/ai/test", headers=HEADERS).text

    assert "needs an address and a model" in html
    assert rig.chat.provider.calls == []


def test_the_settings_routes_need_the_csrf_token(rig: WebChatRig) -> None:
    assert rig.client.put("/ai/settings", data=OLLAMA).status_code == 403
    assert rig.client.post("/ai/test").status_code == 403
    assert rig.chat.store.get("chat.kind") is None


@pytest.mark.parametrize(("method", "path"), [("PUT", "/ai/settings"), ("POST", "/ai/test")])
def test_a_tailnet_host_cannot_use_the_settings_routes(
    rig: WebChatRig, method: str, path: str
) -> None:
    client = TestClient(rig.app, base_url=TAILNET)

    response = client.request(method, path, data=OLLAMA, headers=HEADERS)

    assert response.status_code == 404
    assert rig.chat.store.get("chat.kind") is None
    assert rig.chat.provider.calls == []


def test_a_tailnet_host_never_sees_the_stored_address(rig: WebChatRig) -> None:
    save(rig, **OLLAMA)
    client = TestClient(rig.app, base_url=TAILNET)

    assert "localhost:11434" not in client.get("/settings").text


def test_an_address_with_a_query_key_is_not_echoed_back(rig: WebChatRig) -> None:
    html = save(rig, kind="ollama", base_url="http://localhost:1/?key=fake-key-98765", model="m")

    assert "must not carry a query string" in html
    assert "fake-key-98765" not in html
