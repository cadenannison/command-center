"""The Ollama and OpenAI-compatible chat providers: wire format, URL guard at call time."""

import json
import logging
from typing import cast

import httpx
import pytest
import respx

from chat_support import FAKE_KEY
from command_center.adapters import chat_http
from command_center.adapters.chat_ollama import OllamaChatProvider
from command_center.adapters.chat_openai import ChatKeyIntegration, OpenAICompatibleChatProvider
from command_center.core.chat import ChatMessage
from command_center.core.errors import ChatProviderError, ChatRateLimited, TransientError
from fakes import InMemorySecretStore

MESSAGES = [ChatMessage(role="user", content="hi"), ChatMessage(role="assistant", content="yo")]
SYSTEM = "the system prompt"
OLLAMA = "http://localhost:11434/api/chat"
BASE = "https://192.168.1.20:8080/v1"  # https: a key may not cross plain http beyond loopback


def openai(base_url: str = BASE, key: str | None = FAKE_KEY) -> OpenAICompatibleChatProvider:
    secrets = InMemorySecretStore()
    if key is not None:
        secrets.set("chat", "api_key", key)
    return OpenAICompatibleChatProvider(secrets, base_url=base_url, model="fake-model")


def completion(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": text}}]}
    )


@respx.mock
async def test_ollama_posts_the_system_and_turns_and_returns_the_reply() -> None:
    route = respx.post(OLLAMA).mock(
        return_value=httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})
    )

    reply = await OllamaChatProvider(model="fake-model").complete(MESSAGES, SYSTEM, 99)

    assert reply == "ok"
    assert json.loads(route.calls.last.request.content) == {
        "model": "fake-model",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "yo"},
        ],
        "stream": False,
        "options": {"num_predict": 99},
    }


@respx.mock
async def test_openai_compatible_posts_with_the_bearer_key_and_returns_the_reply() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=completion("ok"))

    reply = await openai(base_url=BASE + "/").complete(MESSAGES, SYSTEM, 50)

    assert reply == "ok"
    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    body = json.loads(request.content)
    assert body["model"] == "fake-model"
    assert body["max_tokens"] == 50
    assert body["messages"][0] == {"role": "system", "content": SYSTEM}
    assert FAKE_KEY not in request.content.decode()  # the key rides in the header only


@respx.mock
async def test_a_local_server_without_a_key_gets_no_authorization_header() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=completion("ok"))

    await openai(key=None).complete(MESSAGES, SYSTEM, 50)

    assert "authorization" not in route.calls.last.request.headers


@respx.mock
@pytest.mark.parametrize("status", [429, 503])
async def test_a_busy_server_is_rate_limited(status: int) -> None:
    respx.post(OLLAMA).mock(return_value=httpx.Response(status))

    with pytest.raises(ChatRateLimited):
        await OllamaChatProvider().complete(MESSAGES, SYSTEM, 9)


@respx.mock
@pytest.mark.parametrize(
    ("status", "text"),
    [(401, "rejected the API key"), (404, "model or endpoint"), (500, "request failed (500)")],
)
async def test_errors_are_fixed_text_even_when_the_server_echoes_secrets(
    status: int, text: str, caplog: pytest.LogCaptureFixture
) -> None:
    echoed = f"Authorization: Bearer {FAKE_KEY} and the prompt {SYSTEM} at {BASE}"
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(status, text=echoed))
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ChatProviderError) as caught:
        await openai().complete(MESSAGES, SYSTEM, 9)

    assert text in str(caught.value)
    assert FAKE_KEY not in str(caught.value) + caplog.text
    assert SYSTEM not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@respx.mock
@pytest.mark.parametrize(
    "side_effect",
    [httpx.ConnectError("refused " + FAKE_KEY), httpx.ReadTimeout("slow " + FAKE_KEY)],
)
async def test_a_transport_failure_does_not_carry_the_transports_text(
    side_effect: Exception,
) -> None:
    respx.post(f"{BASE}/chat/completions").mock(side_effect=side_effect)

    with pytest.raises(ChatProviderError) as caught:
        await openai().complete(MESSAGES, SYSTEM, 9)

    assert FAKE_KEY not in str(caught.value)


@respx.mock
@pytest.mark.parametrize(
    "body",
    cast("list[object]", [{"choices": []}, {"choices": [{"message": {}}]}, ["x"], {}]),
)
async def test_a_malformed_reply_is_a_provider_error(body: object) -> None:
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, json=body))

    with pytest.raises(ChatProviderError, match="malformed"):
        await openai().complete(MESSAGES, SYSTEM, 9)


@respx.mock
async def test_a_reply_that_is_not_json_is_a_provider_error() -> None:
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, text="<html>"))

    with pytest.raises(ChatProviderError, match="malformed"):
        await openai().complete(MESSAGES, SYSTEM, 9)


@respx.mock
async def test_a_redirect_is_not_followed() -> None:
    target = respx.get("http://169.254.169.254/")
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(307, headers={"location": "http://169.254.169.254/"})
    )

    with pytest.raises(ChatProviderError):
        await openai().complete(MESSAGES, SYSTEM, 9)

    assert not target.called


@respx.mock
@pytest.mark.parametrize(
    "base_url",
    [
        "http://169.254.169.254/v1",
        "https://169.254.169.254/v1",
        "http://[fe80::1]/v1",
        "http://metadata.google.internal/v1",
        "http://api.openai.com/v1",  # public host over http
        "http://8.8.8.8/v1",
        "https://localhost/v1?key=" + FAKE_KEY,
        "http://user:" + FAKE_KEY + "@localhost/v1",
        "file:///etc/passwd",
    ],
)
async def test_a_refused_address_is_never_contacted_and_never_echoed(base_url: str) -> None:
    anything = respx.route().mock(return_value=completion("sent"))

    with pytest.raises(ChatProviderError) as caught:
        await openai(base_url=base_url).complete(MESSAGES, SYSTEM, 9)
    with pytest.raises(ChatProviderError):
        await OllamaChatProvider(base_url=base_url).complete(MESSAGES, SYSTEM, 9)

    assert not anything.called
    assert str(caught.value) == "The chat server address is not allowed"


@respx.mock
async def test_a_public_name_that_resolves_to_a_private_address_is_never_contacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolves_privately(_host: str) -> None:
        msg = "Rejected host: resolves to a private, loopback, link-local or non-global address"
        raise ValueError(msg)

    monkeypatch.setattr(chat_http, "ensure_public_host", resolves_privately)
    anything = respx.route().mock(return_value=completion("sent"))

    with pytest.raises(ChatProviderError, match="not allowed"):
        await openai(base_url="https://llm.example.com/v1").complete(MESSAGES, SYSTEM, 9)

    assert not anything.called


@respx.mock
async def test_a_public_https_name_is_resolved_then_called(monkeypatch: pytest.MonkeyPatch) -> None:
    looked_up: list[str] = []

    async def public(host: str) -> None:
        looked_up.append(host)

    monkeypatch.setattr(chat_http, "ensure_public_host", public)
    route = respx.post("https://llm.example.com/v1/chat/completions").mock(
        return_value=completion("hi")
    )

    assert await openai(base_url="https://llm.example.com/v1").complete(MESSAGES, SYSTEM, 9) == "hi"

    assert looked_up == ["llm.example.com"]
    assert route.called


@respx.mock
async def test_a_lookup_timeout_is_a_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(_host: str) -> None:
        msg = "host lookup timed out"
        raise TransientError(msg)

    monkeypatch.setattr(chat_http, "ensure_public_host", slow)
    anything = respx.route().mock(return_value=completion("sent"))

    with pytest.raises(ChatProviderError, match="looked up"):
        await openai(base_url="https://llm.example.com/v1").complete(MESSAGES, SYSTEM, 9)

    assert not anything.called


@respx.mock
@pytest.mark.parametrize("host", ["localhost", "192.168.1.5", "[::1]"])
async def test_localhost_and_literal_addresses_are_not_looked_up(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(_name: str) -> set[str]:
        msg = "this host must not be looked up"
        raise AssertionError(msg)

    monkeypatch.setattr(chat_http, "ensure_public_host", fail)
    monkeypatch.setattr(chat_http, "resolve_addresses", fail)
    route = respx.post(f"http://{host}:8000/v1/chat/completions").mock(
        return_value=completion("ok")
    )

    provider = openai(base_url=f"http://{host}:8000/v1", key=None)  # no key: it may not ride http
    assert await provider.complete(MESSAGES, SYSTEM, 9) == "ok"
    assert route.called


@respx.mock
@pytest.mark.parametrize("host", ["gpu-box", "mac.local"])
@pytest.mark.parametrize("address", ["192.168.1.5", "10.0.0.7", "127.0.0.1", "fd12::5"])
async def test_a_local_name_that_resolves_to_this_machine_or_lan_is_called(
    host: str, address: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolved(_name: str) -> set[str]:
        return {address}

    monkeypatch.setattr(chat_http, "resolve_addresses", resolved)
    route = respx.post(f"http://{host}:8000/v1/chat/completions").mock(
        return_value=completion("ok")
    )

    provider = openai(base_url=f"http://{host}:8000/v1", key=None)  # no key: it may not ride http
    assert await provider.complete(MESSAGES, SYSTEM, 9) == "ok"
    assert route.called


@respx.mock
@pytest.mark.parametrize("host", ["instance-data", "gpu-box", "mac.local"])
@pytest.mark.parametrize(
    "address",
    [
        "169.254.169.254",
        "fe80::1",
        "100.100.100.200",
        "0.0.0.0",  # noqa: S104  (the unspecified address is what is being refused)
        "224.0.0.1",
        "8.8.8.8",
    ],
)
async def test_a_local_name_that_resolves_to_a_refused_address_is_never_contacted(
    host: str, address: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolved(_name: str) -> set[str]:
        return {"192.168.1.5", address}

    monkeypatch.setattr(chat_http, "resolve_addresses", resolved)
    anything = respx.route().mock(return_value=completion("sent"))

    with pytest.raises(ChatProviderError, match="not allowed"):
        await openai(base_url=f"http://{host}:8000/v1").complete(MESSAGES, SYSTEM, 9)

    assert not anything.called


@respx.mock
async def test_a_local_name_that_does_not_resolve_is_never_contacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def nothing(_name: str) -> set[str]:
        return set()

    monkeypatch.setattr(chat_http, "resolve_addresses", nothing)
    anything = respx.route().mock(return_value=completion("sent"))

    with pytest.raises(ChatProviderError, match="looked up"):
        await openai(base_url="http://gpu-box:8000/v1").complete(MESSAGES, SYSTEM, 9)

    assert not anything.called


async def test_the_key_integration_checks_only_that_a_key_was_entered() -> None:
    integration = ChatKeyIntegration()

    assert integration.name == "chat"
    assert (await integration.validate({"api_key": FAKE_KEY})).ok is True
    assert (await integration.validate({"api_key": "  "})).ok is False
    assert (await integration.validate({})).ok is False
