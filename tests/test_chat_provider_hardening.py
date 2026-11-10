"""Chat provider hardening: where the key travels, what skips the address check, the reply cap.

Decisions 0220-0223. Each case fails with the old code and passes with the new.
"""

import gzip
import json
import logging
import traceback
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import respx

from chat_support import FAKE_KEY
from command_center.adapters import chat_http
from command_center.adapters.chat_ollama import OllamaChatProvider
from command_center.adapters.chat_openai import OpenAICompatibleChatProvider
from command_center.adapters.summary_gemini import GeminiChatProvider
from command_center.core.chat import ChatMessage
from command_center.core.errors import ChatProviderError
from fakes import InMemorySecretStore

MESSAGES = [ChatMessage(role="user", content="hi")]
SYSTEM = "fake-system-prompt-needle"
NOT_ALLOWED = "The chat server address is not allowed"
KEY_REFUSED = "The chat server key is not sent over plain http to this address; use https"


def openai(base_url: str, key: str | None = FAKE_KEY) -> OpenAICompatibleChatProvider:
    secrets = InMemorySecretStore()
    if key is not None:
        secrets.set("chat", "api_key", key)
    return OpenAICompatibleChatProvider(secrets, base_url=base_url, model="fake-model")


def completion(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": text}}]}
    )


def resolving_to(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> list[str]:
    looked_up: list[str] = []

    async def resolved(name: str) -> set[str]:
        looked_up.append(name)
        return set(addresses)

    monkeypatch.setattr(chat_http, "resolve_addresses", resolved)
    return looked_up


# --- 1. the key is never sent over plain http beyond loopback --------------------------------


@respx.mock
@pytest.mark.parametrize(
    "host", ["192.168.1.20", "10.0.0.7", "[fd12::5]", "gpu-box", "mac.local", "app.localhost"]
)
async def test_a_key_is_never_sent_over_http_to_a_non_loopback_host(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = resolving_to(monkeypatch, "127.0.0.1")
    anything = respx.route().mock(return_value=completion("sent"))

    with pytest.raises(ChatProviderError) as caught:
        _ = await openai(f"http://{host}:8080/v1").complete(MESSAGES, SYSTEM, 9)

    assert not anything.called
    assert str(caught.value) == KEY_REFUSED
    assert FAKE_KEY not in str(caught.value)


@respx.mock
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.9.9.9", "[::1]"])
async def test_a_key_is_sent_over_http_to_a_loopback_name_or_address(host: str) -> None:
    route = respx.post(f"http://{host}:8080/v1/chat/completions").mock(
        return_value=completion("ok")
    )

    assert await openai(f"http://{host}:8080/v1").complete(MESSAGES, SYSTEM, 9) == "ok"

    assert route.calls.last.request.headers["authorization"] == f"Bearer {FAKE_KEY}"


@respx.mock
@pytest.mark.parametrize("host", ["192.168.1.20", "gpu-box"])
async def test_a_key_is_sent_over_https_to_a_lan_host(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = resolving_to(monkeypatch, "192.168.1.20")
    route = respx.post(f"https://{host}:8080/v1/chat/completions").mock(
        return_value=completion("ok")
    )

    assert await openai(f"https://{host}:8080/v1").complete(MESSAGES, SYSTEM, 9) == "ok"

    assert route.calls.last.request.headers["authorization"] == f"Bearer {FAKE_KEY}"


@respx.mock
@pytest.mark.parametrize("key", [None, "   "])
async def test_a_lan_server_that_needs_no_key_is_still_called_over_http(key: str | None) -> None:
    route = respx.post("http://192.168.1.20:8080/v1/chat/completions").mock(
        return_value=completion("ok")
    )

    assert await openai("http://192.168.1.20:8080/v1", key).complete(MESSAGES, SYSTEM, 9) == "ok"

    assert "authorization" not in route.calls.last.request.headers


# --- 2. only the exact name localhost skips the address check ---------------------------------


@respx.mock
@pytest.mark.parametrize("make", ["openai", "ollama"])
@pytest.mark.parametrize("address", ["8.8.8.8", "169.254.169.254", "100.100.100.200"])
async def test_a_dot_localhost_name_resolving_to_a_refused_address_is_never_contacted(
    make: str, address: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = resolving_to(monkeypatch, address)
    anything = respx.route().mock(return_value=completion("sent"))
    provider = (
        openai("http://app.localhost:8080/v1", None)
        if make == "openai"
        else OllamaChatProvider(base_url="http://app.localhost:8080")
    )

    with pytest.raises(ChatProviderError) as caught:
        _ = await provider.complete(MESSAGES, SYSTEM, 9)

    assert str(caught.value) == NOT_ALLOWED
    assert not anything.called


@respx.mock
async def test_a_dot_localhost_name_that_does_not_resolve_is_never_contacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = resolving_to(monkeypatch)
    anything = respx.route().mock(return_value=completion("sent"))

    with pytest.raises(ChatProviderError, match="looked up"):
        _ = await openai("http://app.localhost:8080/v1", None).complete(MESSAGES, SYSTEM, 9)

    assert not anything.called


@respx.mock
async def test_a_dot_localhost_name_resolving_to_this_machine_is_called_after_a_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up = resolving_to(monkeypatch, "127.0.0.1")
    route = respx.post("http://app.localhost:8080/v1/chat/completions").mock(
        return_value=completion("ok")
    )

    assert await openai("http://app.localhost:8080/v1", None).complete(MESSAGES, SYSTEM, 9) == "ok"

    assert looked_up == ["app.localhost"]
    assert route.called


@respx.mock
async def test_the_exact_name_localhost_is_still_not_looked_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up = resolving_to(monkeypatch, "8.8.8.8")
    route = respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=completion("ok")
    )

    assert await openai("http://localhost:8080/v1").complete(MESSAGES, SYSTEM, 9) == "ok"

    assert looked_up == []
    assert route.called


# --- 3. the reply is capped while it streams --------------------------------------------------

CHUNK = b"x" * 65_536
CHUNKS = 40  # 2.5 MB if it were all read
TOO_LARGE = "The chat server sent a reply that is too large"


class CountingStream(httpx.AsyncByteStream):
    """A body that counts the chunks the client actually pulled."""

    def __init__(self) -> None:
        self.pulled = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(CHUNKS):
            self.pulled += 1
            yield CHUNK


@respx.mock
async def test_a_reply_past_the_cap_aborts_while_streaming_with_fixed_text() -> None:
    stream = CountingStream()
    _ = respx.post("http://127.0.0.1:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, stream=stream)
    )

    with pytest.raises(ChatProviderError) as caught:
        _ = await openai("http://127.0.0.1:8080/v1").complete(MESSAGES, SYSTEM, 9)

    assert str(caught.value) == TOO_LARGE
    assert 1 <= stream.pulled <= 20  # stopped near 1 MB, not after 2.5 MB


@respx.mock
async def test_a_reply_that_declares_a_size_past_the_cap_is_not_read_at_all() -> None:
    stream = CountingStream()
    _ = respx.post("http://127.0.0.1:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, headers={"content-length": "5000000"}, stream=stream)
    )

    with pytest.raises(ChatProviderError, match="too large"):
        _ = await openai("http://127.0.0.1:8080/v1").complete(MESSAGES, SYSTEM, 9)

    assert stream.pulled == 0


@respx.mock
async def test_a_small_compressed_reply_that_inflates_past_the_cap_is_refused() -> None:
    body = json.dumps({"choices": [{"message": {"content": "a" * 3_000_000}}]}).encode()
    squeezed = gzip.compress(body)
    assert len(squeezed) < 100_000
    _ = respx.post("http://127.0.0.1:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, headers={"content-encoding": "gzip"}, content=squeezed)
    )

    with pytest.raises(ChatProviderError, match="too large"):
        _ = await openai("http://127.0.0.1:8080/v1").complete(MESSAGES, SYSTEM, 9)


@respx.mock
async def test_a_large_reply_under_the_cap_is_returned_whole() -> None:
    text = "a" * 900_000
    _ = respx.post("http://127.0.0.1:8080/v1/chat/completions").mock(return_value=completion(text))

    assert await openai("http://127.0.0.1:8080/v1").complete(MESSAGES, SYSTEM, 9) == text


@respx.mock
async def test_the_ollama_reply_is_capped_too() -> None:
    stream = CountingStream()
    _ = respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(200, stream=stream)
    )

    with pytest.raises(ChatProviderError, match="too large"):
        _ = await OllamaChatProvider().complete(MESSAGES, SYSTEM, 9)

    assert stream.pulled <= 20


@respx.mock
async def test_an_error_status_is_decided_before_the_body_is_read() -> None:
    stream = CountingStream()
    _ = respx.post("http://127.0.0.1:8080/v1/chat/completions").mock(
        return_value=httpx.Response(500, stream=stream)
    )

    with pytest.raises(ChatProviderError, match=r"request failed \(500\)"):
        _ = await openai("http://127.0.0.1:8080/v1").complete(MESSAGES, SYSTEM, 9)

    assert stream.pulled == 0


@respx.mock
async def test_a_connection_that_drops_mid_reply_is_a_fixed_text_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def dropping() -> AsyncIterator[bytes]:
        yield b'{"choices": '
        msg = f"connection lost {FAKE_KEY}"
        raise httpx.ReadError(msg)

    _ = respx.post("http://127.0.0.1:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=dropping())
    )
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ChatProviderError) as caught:
        _ = await openai("http://127.0.0.1:8080/v1").complete(MESSAGES, SYSTEM, 9)

    assert FAKE_KEY not in str(caught.value) + caplog.text


# --- 4. any other SDK exception becomes fixed text --------------------------------------------

SECRET_TEXT = "fake-sdk-message with the system prompt " + SYSTEM


class _Models:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def generate_content(self, **_kwargs: Any) -> object:  # noqa: ANN401
        raise self._error


class _Aio:
    def __init__(self, error: BaseException, close_error: BaseException | None) -> None:
        self.models = _Models(error)
        self._close_error = close_error

    async def aclose(self) -> None:
        if self._close_error is not None:
            raise self._close_error


class _Client:
    def __init__(self, error: BaseException, close_error: BaseException | None = None) -> None:
        self.aio = _Aio(error, close_error)
        self._close_error = close_error

    def close(self) -> None:
        if self._close_error is not None:
            raise self._close_error


@pytest.mark.parametrize(
    "error", [RuntimeError(SECRET_TEXT), ValueError(SECRET_TEXT), KeyError(SECRET_TEXT)]
)
async def test_an_unexpected_gemini_sdk_exception_is_fixed_text(error: Exception) -> None:
    secrets = InMemorySecretStore()
    secrets.set("gemini", "api_key", FAKE_KEY)
    provider = GeminiChatProvider(
        secrets,
        model="fake-model",
        client_factory=lambda _key: _Client(error),  # pyright: ignore[reportArgumentType]
    )

    with pytest.raises(ChatProviderError) as caught:
        _ = await provider.complete(MESSAGES, SYSTEM, 9)

    assert str(caught.value) == "Gemini request failed"
    shown = "".join(traceback.format_exception(caught.value))
    assert SECRET_TEXT not in shown
    assert SYSTEM not in shown


def _gemini(client_factory: Callable[[str], object]) -> GeminiChatProvider:
    secrets = InMemorySecretStore()
    secrets.set("gemini", "api_key", FAKE_KEY)
    return GeminiChatProvider(
        secrets,
        model="fake-model",
        client_factory=client_factory,  # pyright: ignore[reportArgumentType]
    )


async def test_a_gemini_failure_while_closing_the_client_does_not_replace_the_fixed_error() -> None:
    provider = _gemini(
        lambda _key: _Client(RuntimeError(SECRET_TEXT), close_error=RuntimeError(SECRET_TEXT))
    )

    with pytest.raises(ChatProviderError) as caught:
        _ = await provider.complete(MESSAGES, SYSTEM, 9)

    assert str(caught.value) == "Gemini request failed"
    assert SECRET_TEXT not in "".join(traceback.format_exception(caught.value))


async def test_a_gemini_failure_while_closing_after_a_good_reply_is_not_raised() -> None:
    class _Models:
        async def generate_content(self, **_kwargs: Any) -> object:  # noqa: ANN401
            return type("Response", (), {"text": "the answer"})()

    client = _Client(RuntimeError("unused"), close_error=RuntimeError(SECRET_TEXT))
    client.aio.models = _Models()  # pyright: ignore[reportAttributeAccessIssue]

    assert await _gemini(lambda _key: client).complete(MESSAGES, SYSTEM, 9) == "the answer"


async def test_a_gemini_client_factory_failure_is_fixed_text() -> None:
    def broken(_key: str) -> object:
        raise RuntimeError(SECRET_TEXT)

    with pytest.raises(ChatProviderError) as caught:
        _ = await _gemini(broken).complete(MESSAGES, SYSTEM, 9)

    assert str(caught.value) == "Gemini request failed"
    assert SECRET_TEXT not in "".join(traceback.format_exception(caught.value))


# --- 5. nothing in the environment may route a chat call through a proxy -----------------------


class _SpyClient(httpx.AsyncClient):
    instances: list["_SpyClient"] = []  # noqa: RUF012

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        _SpyClient.instances.append(self)


@respx.mock
@pytest.mark.parametrize("make", ["openai", "ollama"])
async def test_a_chat_call_ignores_proxy_settings_in_the_environment(
    make: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://fake-proxy.example:3128")
    monkeypatch.setenv("ALL_PROXY", "http://fake-proxy.example:3128")
    monkeypatch.setattr(chat_http.httpx, "AsyncClient", _SpyClient)
    _SpyClient.instances.clear()
    _ = respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "ok"}})
    )
    _ = respx.post("http://localhost:11434/v1/chat/completions").mock(return_value=completion("ok"))
    provider = openai("http://localhost:11434/v1") if make == "openai" else OllamaChatProvider()

    assert await provider.complete(MESSAGES, SYSTEM, 9) == "ok"

    assert [client.trust_env for client in _SpyClient.instances] == [False]


# --- 6. a trailing dot makes a different DNS name: it is looked up and gets no key over http ----


@respx.mock
async def test_localhost_with_a_trailing_dot_is_looked_up_like_any_local_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up = resolving_to(monkeypatch, "169.254.169.254")
    anything = respx.route().mock(return_value=completion("sent"))

    with pytest.raises(ChatProviderError) as caught:
        _ = await openai("http://localhost.:8080/v1", None).complete(MESSAGES, SYSTEM, 9)

    assert looked_up == ["localhost."]  # the name the request will use, dot included
    assert str(caught.value) == NOT_ALLOWED
    assert not anything.called


@respx.mock
async def test_a_key_is_not_sent_over_http_to_localhost_with_a_trailing_dot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = resolving_to(monkeypatch, "127.0.0.1")
    anything = respx.route().mock(return_value=completion("sent"))

    with pytest.raises(ChatProviderError) as caught:
        _ = await openai("http://localhost.:8080/v1").complete(MESSAGES, SYSTEM, 9)

    assert str(caught.value) == KEY_REFUSED
    assert not anything.called
