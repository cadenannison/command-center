# ruff: noqa: SLF001  (these tests reach into the SDK client's own transport on purpose)
"""Summary provider and city search hardening: fixed-text failures, no proxy, a capped reply.

Decisions 0245 (any other exception) and 0246 (proxy settings, the geocoder's reply cap).
Each case fails with the old code and passes with the new.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
import httpx2  # the Gemini SDK's default client library (decision 0245); not imported by src
import pytest
import respx

from command_center.adapters import summary_gemini, summary_ollama, weather_geocode
from command_center.adapters.http_cap import MAX_REPLY_BYTES
from command_center.adapters.summary_gemini import (
    GeminiChatProvider,
    GeminiIntegration,
    GeminiSummaryProvider,
)
from command_center.adapters.summary_ollama import OllamaSummaryProvider
from command_center.adapters.weather_geocode import URL, OpenMeteoGeocoder
from command_center.core.chat import ChatMessage
from command_center.core.errors import (
    ChatProviderError,
    FatalError,
    SummaryProviderError,
    TransientError,
)
from fakes import InMemorySecretStore

SDK: Any = summary_gemini  # the SDK client builders are private; Any keeps the private access out
NEEDLE = "fake-needle-key-and-prompt-text"
OLLAMA_URL = "http://localhost:11434/api/generate"


class _Models:
    def __init__(self, outcome: BaseException) -> None:
        self._outcome = outcome

    async def generate_content(self, **_: Any) -> object:  # noqa: ANN401
        raise self._outcome


class _Aio:
    def __init__(self, outcome: BaseException) -> None:
        self.models = _Models(outcome)

    async def aclose(self) -> None:
        return None


class _Client:
    def __init__(self, outcome: BaseException) -> None:
        self.aio = _Aio(outcome)

    def close(self) -> None:
        return None


def gemini_failing_with(outcome: BaseException) -> GeminiSummaryProvider:
    secrets = InMemorySecretStore()
    secrets.set("gemini", "api_key", "fake-gemini-key-ABCD1234")
    return GeminiSummaryProvider(secrets, client_factory=lambda _key: _Client(outcome))  # pyright: ignore[reportArgumentType]


# --- 2. any other exception is a fixed-text summary provider error -----------------------------


@pytest.mark.parametrize("error", [RuntimeError(NEEDLE), ValueError(NEEDLE), KeyError(NEEDLE)])
async def test_gemini_summary_turns_any_other_exception_into_fixed_text(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    with pytest.raises(SummaryProviderError) as caught:
        _ = await gemini_failing_with(error).summarize("the prompt")

    assert str(caught.value) == "Gemini request failed"
    assert NEEDLE not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    assert NEEDLE not in caplog.text
    assert [vars(r)["error_class"] for r in caplog.records if "error_class" in vars(r)] == [
        type(error).__name__
    ]
    assert NEEDLE not in repr([vars(record) for record in caplog.records])


async def test_gemini_summary_does_not_swallow_a_cancellation() -> None:
    with pytest.raises(asyncio.CancelledError):
        _ = await gemini_failing_with(asyncio.CancelledError()).summarize("the prompt")


async def test_gemini_summary_client_construction_failure_is_fixed_text() -> None:
    secrets = InMemorySecretStore()
    secrets.set("gemini", "api_key", "fake-gemini-key-ABCD1234")

    def broken(_key: str) -> Any:  # noqa: ANN401
        raise RuntimeError(NEEDLE)

    provider = GeminiSummaryProvider(secrets, client_factory=broken)

    with pytest.raises(SummaryProviderError) as caught:
        _ = await provider.summarize("the prompt")

    assert NEEDLE not in str(caught.value)


@respx.mock
@pytest.mark.parametrize("error", [RuntimeError(NEEDLE), ValueError(NEEDLE), OSError(NEEDLE)])
async def test_ollama_summary_turns_any_other_exception_into_fixed_text(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    _ = respx.post(OLLAMA_URL).mock(side_effect=error)

    with pytest.raises(SummaryProviderError) as caught:
        _ = await OllamaSummaryProvider(model="fake-model").summarize("the prompt")

    assert str(caught.value) == "Ollama request failed"
    assert caught.value.__suppress_context__ is True
    assert NEEDLE not in caplog.text
    assert [vars(r)["error_class"] for r in caplog.records if "error_class" in vars(r)] == [
        type(error).__name__
    ]
    assert NEEDLE not in repr([vars(record) for record in caplog.records])


class _CancelledClient(httpx.AsyncClient):
    async def post(self, *_args: Any, **_kwargs: Any) -> httpx.Response:  # noqa: ANN401
        raise asyncio.CancelledError


async def test_ollama_summary_does_not_swallow_a_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(summary_ollama.httpx, "AsyncClient", _CancelledClient)

    with pytest.raises(asyncio.CancelledError):
        _ = await OllamaSummaryProvider(model="fake-model").summarize("the prompt")


# --- 3. neither client reads proxy settings from the environment -------------------------------


class _SpyClient(httpx.AsyncClient):
    instances: list["_SpyClient"] = []  # noqa: RUF012

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        _SpyClient.instances.append(self)


@pytest.fixture
def proxy_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://fake-proxy.example:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://fake-proxy.example:3128")
    monkeypatch.setenv("ALL_PROXY", "http://fake-proxy.example:3128")
    _SpyClient.instances.clear()


@respx.mock
@pytest.mark.usefixtures("proxy_in_the_environment")
async def test_the_ollama_summary_client_ignores_proxy_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(summary_ollama.httpx, "AsyncClient", _SpyClient)
    _ = respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json={"response": "{}"}))

    with pytest.raises(
        SummaryProviderError
    ):  # an empty summary is malformed; only the client matters
        _ = await OllamaSummaryProvider(model="fake-model").summarize("p")

    assert [client.trust_env for client in _SpyClient.instances] == [False]


@respx.mock
@pytest.mark.usefixtures("proxy_in_the_environment")
async def test_the_geocoder_client_ignores_proxy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(weather_geocode.httpx, "AsyncClient", _SpyClient)
    _ = respx.get(URL).mock(return_value=httpx.Response(200, json={}))

    assert await OpenMeteoGeocoder().search("Provo") == []

    assert [client.trust_env for client in _SpyClient.instances] == [False]


@pytest.mark.usefixtures("proxy_in_the_environment")
async def test_the_gemini_sdk_clients_ignore_proxy_settings() -> None:
    for factory in (SDK._default_client, SDK._validation_client):
        client: Any = factory("fake-gemini-key-ABCD1234")
        try:
            transport = client._api_client  # the SDK exposes its httpx clients only here
            assert transport._async_httpx_client.trust_env is False
            assert transport._httpx_client.trust_env is False
        finally:
            await client.aio.aclose()
            client.close()


def test_the_gemini_client_keeps_its_request_timeout() -> None:
    client: Any = SDK._default_client("fake-gemini-key-ABCD1234")
    try:
        assert client._api_client._http_options.timeout == 30_000
    finally:
        client.close()


# --- 4. the geocoder reads its reply as a stream and stops at the shared cap -------------------

CHUNK = b"x" * 65_536
CHUNKS = 200


class CountingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.pulled = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(CHUNKS):
            self.pulled += 1
            yield CHUNK


def test_the_geocoder_shares_the_chat_replys_cap() -> None:
    from command_center.adapters import chat_http  # noqa: PLC0415

    assert MAX_REPLY_BYTES == 1_048_576
    assert chat_http.MAX_REPLY_BYTES == MAX_REPLY_BYTES


@respx.mock
async def test_a_geocoder_reply_past_the_cap_aborts_while_streaming() -> None:
    stream = CountingStream()
    _ = respx.get(URL).mock(return_value=httpx.Response(200, stream=stream))

    with pytest.raises(FatalError, match="too large") as caught:
        _ = await OpenMeteoGeocoder().search("Provo")

    assert stream.pulled <= 20  # 1 MiB is 16 chunks of 64 KiB, not 200
    assert "Provo" not in str(caught.value)


@respx.mock
async def test_a_geocoder_reply_that_declares_a_size_past_the_cap_is_not_read() -> None:
    stream = CountingStream()
    _ = respx.get(URL).mock(
        return_value=httpx.Response(200, headers={"content-length": "5000000"}, stream=stream)
    )

    with pytest.raises(FatalError, match="too large"):
        _ = await OpenMeteoGeocoder().search("Provo")

    assert stream.pulled == 0


@respx.mock
async def test_an_injected_geocoder_client_is_capped_too() -> None:
    stream = CountingStream()
    _ = respx.get(URL).mock(return_value=httpx.Response(200, stream=stream))

    async with httpx.AsyncClient() as client:
        with pytest.raises(FatalError, match="too large"):
            _ = await OpenMeteoGeocoder(client=client).search("Provo")

    assert stream.pulled <= 20


@respx.mock
async def test_a_geocoder_error_status_does_not_read_the_body() -> None:
    stream = CountingStream()
    _ = respx.get(URL).mock(return_value=httpx.Response(500, stream=stream))

    with pytest.raises(TransientError, match=r"unavailable \(500\)"):
        _ = await OpenMeteoGeocoder().search("Provo")

    assert stream.pulled == 0


@respx.mock
async def test_a_geocoder_reply_that_cannot_be_decoded_is_a_fixed_text_fatal_error() -> None:
    _ = respx.get(URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=httpx.ByteStream(b"this is not gzip"),  # decoded only when the body is read
        )
    )

    with pytest.raises(FatalError, match="unexpected response") as caught:
        _ = await OpenMeteoGeocoder().search("Provo")

    assert "Provo" not in str(caught.value)


async def test_gemini_summary_does_not_swallow_a_cancellation_from_the_client_factory() -> None:
    secrets = InMemorySecretStore()
    secrets.set("gemini", "api_key", "fake-gemini-key-ABCD1234")

    def cancelled(_key: str) -> Any:  # noqa: ANN401
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        _ = await GeminiSummaryProvider(secrets, client_factory=cancelled).summarize("p")


# --- 5. the SDK's default client library is httpx2, whose errors are not httpx.HTTPError -------

HTTPX2_ERRORS = [
    httpx2.ConnectError(NEEDLE),
    httpx2.ReadTimeout(NEEDLE),
    httpx2.RemoteProtocolError(NEEDLE),
]


def test_the_sdks_default_client_library_is_httpx2_and_its_errors_are_not_httpx_errors() -> None:
    client: Any = SDK._default_client("fake-gemini-key-ABCD1234")
    try:
        assert type(client._api_client._async_httpx_client).__module__.startswith("google.genai")
        assert isinstance(client._api_client._async_httpx_client, httpx2.AsyncClient)
    finally:
        client.close()
    assert not isinstance(HTTPX2_ERRORS[0], httpx.HTTPError)


@pytest.mark.parametrize("error", HTTPX2_ERRORS)
async def test_gemini_summary_reports_an_unreachable_server_for_a_network_error(
    error: Exception,
) -> None:
    with pytest.raises(SummaryProviderError) as caught:
        _ = await gemini_failing_with(error).summarize("the prompt")

    assert str(caught.value) == "Gemini is unreachable"


@pytest.mark.parametrize("error", HTTPX2_ERRORS)
async def test_gemini_chat_reports_an_unreachable_server_for_a_network_error(
    error: Exception,
) -> None:
    secrets = InMemorySecretStore()
    secrets.set("gemini", "api_key", "fake-gemini-key-ABCD1234")
    provider = GeminiChatProvider(secrets, client_factory=lambda _key: _Client(error))  # pyright: ignore[reportArgumentType]

    with pytest.raises(ChatProviderError) as caught:
        _ = await provider.complete([ChatMessage(role="user", content="hi")], "system", 9)

    assert str(caught.value) == "Gemini is unreachable"


class _CountTokens:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def count_tokens(self, **_: Any) -> object:  # noqa: ANN401
        raise self._error


@pytest.mark.parametrize("error", HTTPX2_ERRORS)
async def test_the_gemini_key_check_treats_a_network_error_as_transient(error: Exception) -> None:
    client = _Client(error)
    client.aio.models = _CountTokens(error)  # pyright: ignore[reportAttributeAccessIssue]
    integration = GeminiIntegration(client_factory=lambda _key: client)  # pyright: ignore[reportArgumentType]

    with pytest.raises(TransientError, match="Gemini is unreachable") as caught:
        _ = await integration.validate({"api_key": "fake-gemini-key-ABCD1234"})

    assert NEEDLE not in str(caught.value)
