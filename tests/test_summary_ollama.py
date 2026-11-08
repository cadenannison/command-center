"""OllamaSummaryProvider against a mocked local endpoint (no network)."""

import json

import httpx
import pytest
import respx

from command_center.adapters.summary_ollama import OllamaSummaryProvider
from command_center.core.errors import SummaryProviderError, SummaryRateLimited
from command_center.core.summary import DailySummary

URL = "http://localhost:11434/api/generate"
GOOD = DailySummary(headline="Busy day", priorities=["Essay"], heads_up=[])


def provider() -> OllamaSummaryProvider:
    return OllamaSummaryProvider(model="fake-model")


def reply(summary: DailySummary = GOOD) -> httpx.Response:
    return httpx.Response(200, json={"response": summary.model_dump_json(), "done": True})


@respx.mock
async def test_posts_json_mode_to_the_local_endpoint_and_parses_the_reply() -> None:
    route = respx.post(URL).mock(return_value=reply())
    assert await provider().summarize("the prompt") == GOOD
    sent = json.loads(route.calls.last.request.content)
    assert sent == {
        "model": "fake-model",
        "prompt": "the prompt",
        "format": "json",
        "stream": False,
    }


def test_name() -> None:
    assert provider().name == "ollama"


@respx.mock
@pytest.mark.parametrize("status", [429, 503])
async def test_busy_server_is_rate_limited(status: int) -> None:
    respx.post(URL).mock(return_value=httpx.Response(status))
    with pytest.raises(SummaryRateLimited):
        await provider().summarize("p")


@respx.mock
async def test_unknown_model_says_to_pull_it() -> None:
    respx.post(URL).mock(return_value=httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(SummaryProviderError, match="pull it"):
        await provider().summarize("p")


@respx.mock
async def test_server_error_carries_only_the_status() -> None:
    respx.post(URL).mock(return_value=httpx.Response(500, text="the prompt echoed back"))
    with pytest.raises(SummaryProviderError) as caught:
        await provider().summarize("p")
    assert str(caught.value) == "Ollama request failed (500)"


@respx.mock
async def test_unreachable_server_is_a_provider_error() -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(SummaryProviderError, match="unreachable"):
        await provider().summarize("p")


@respx.mock
async def test_timeout_is_a_provider_error() -> None:
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(SummaryProviderError, match="timed out"):
        await provider().summarize("p")


@respx.mock
@pytest.mark.parametrize(
    "body",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=["list"]),
        httpx.Response(200, json={"nope": 1}),
        httpx.Response(200, json={"response": 5}),
        httpx.Response(200, json={"response": "not json"}),
        httpx.Response(200, json={"response": '{"headline": 1}'}),
    ],
)
async def test_malformed_reply_is_a_provider_error(body: httpx.Response) -> None:
    respx.post(URL).mock(return_value=body)
    with pytest.raises(SummaryProviderError, match="malformed"):
        await provider().summarize("p")


@respx.mock
async def test_trailing_slash_in_base_url_is_tolerated() -> None:
    route = respx.post(URL).mock(return_value=reply())
    await OllamaSummaryProvider(model="m", base_url="http://localhost:11434/").summarize("p")
    assert route.called
