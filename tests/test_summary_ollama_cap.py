"""The Ollama summary reply is read as a stream and stopped at the shared cap (decision 0288).

Same shape as the geocoder cases in test_summary_provider_hardening.py: an oversize reply, a
declared length over the cap, and a chunked reply with no length at all.
"""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import respx

from command_center.adapters import summary_ollama
from command_center.adapters.http_cap import MAX_REPLY_BYTES
from command_center.adapters.summary_ollama import OllamaSummaryProvider
from command_center.core.errors import SummaryProviderError, SummaryRateLimited
from command_center.core.summary import DailySummary

URL = "http://localhost:11434/api/generate"
NEEDLE = "fake-needle-prompt-text"
CHUNK = b"x" * 65_536
CHUNKS = 200
GOOD = DailySummary(headline="Busy day", priorities=["Essay"], heads_up=[])


class CountingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.pulled = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(CHUNKS):
            self.pulled += 1
            yield CHUNK


def provider() -> OllamaSummaryProvider:
    return OllamaSummaryProvider(model="fake-model")


@respx.mock
async def test_a_reply_body_over_the_cap_is_a_fixed_text_error() -> None:
    body = b"x" * (MAX_REPLY_BYTES + 1)
    _ = respx.post(URL).mock(return_value=httpx.Response(200, content=body))

    with pytest.raises(SummaryProviderError, match="too large") as caught:
        _ = await provider().summarize(NEEDLE)

    assert NEEDLE not in str(caught.value)


@respx.mock
async def test_a_chunked_reply_with_no_length_is_abandoned_at_the_cap() -> None:
    stream = CountingStream()
    _ = respx.post(URL).mock(
        return_value=httpx.Response(200, headers={"transfer-encoding": "chunked"}, stream=stream)
    )

    with pytest.raises(SummaryProviderError, match="too large"):
        _ = await provider().summarize(NEEDLE)

    assert stream.pulled <= 20  # 1 MiB is 16 chunks of 64 KiB, not 200


@respx.mock
async def test_a_declared_length_over_the_cap_is_refused_before_any_read() -> None:
    stream = CountingStream()
    _ = respx.post(URL).mock(
        return_value=httpx.Response(200, headers={"content-length": "5000000"}, stream=stream)
    )

    with pytest.raises(SummaryProviderError, match="too large"):
        _ = await provider().summarize(NEEDLE)

    assert stream.pulled == 0


@respx.mock
@pytest.mark.parametrize("status", [404, 500])
async def test_an_error_status_does_not_read_the_body(status: int) -> None:
    stream = CountingStream()
    _ = respx.post(URL).mock(return_value=httpx.Response(status, stream=stream))

    with pytest.raises(SummaryProviderError):
        _ = await provider().summarize(NEEDLE)

    assert stream.pulled == 0


@respx.mock
async def test_a_busy_status_does_not_read_the_body() -> None:
    stream = CountingStream()
    _ = respx.post(URL).mock(return_value=httpx.Response(429, stream=stream))

    with pytest.raises(SummaryRateLimited):
        _ = await provider().summarize(NEEDLE)

    assert stream.pulled == 0


@respx.mock
async def test_a_reply_just_under_the_cap_still_parses() -> None:
    envelope = json.dumps({"response": GOOD.model_dump_json(), "done": True})
    body = envelope + " " * (MAX_REPLY_BYTES - len(envelope) - 1)
    assert len(body) < MAX_REPLY_BYTES
    _ = respx.post(URL).mock(return_value=httpx.Response(200, content=body.encode()))

    assert await provider().summarize("p") == GOOD


class _CancelledOnStream(httpx.AsyncClient):
    @asynccontextmanager
    async def stream(self, *_args: Any, **_kwargs: Any) -> AsyncGenerator[httpx.Response]:  # noqa: ANN401
        raise asyncio.CancelledError
        yield  # pragma: no cover  (makes this a generator for asynccontextmanager)


async def test_a_cancellation_while_streaming_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(summary_ollama.httpx, "AsyncClient", _CancelledOnStream)

    with pytest.raises(asyncio.CancelledError):
        _ = await provider().summarize(NEEDLE)
