"""GeminiSummaryProvider over a fake SDK client: key from the secret store, errors translated."""

from typing import Any, cast

import httpx
import pytest
from google.genai import errors

from command_center.adapters.summary_gemini import DEFAULT_MODEL, GeminiSummaryProvider
from command_center.core.errors import SecretStoreError, SummaryProviderError, SummaryRateLimited
from command_center.core.summary import DailySummary
from fake_adapter import UnavailableSecretStore
from fakes import InMemorySecretStore

KEY = "fake-gemini-key-ABCD1234"
GOOD = DailySummary(headline="Busy day", priorities=["Essay"], heads_up=["Quiz Friday"])


class _Response:
    def __init__(self, text: str | None) -> None:
        self.text = text


class _Models:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> _Response:  # noqa: ANN401
        self.calls.append(kwargs)
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return _Response(cast("str | None", self._outcome))


class _Aio:
    def __init__(self, models: _Models) -> None:
        self.models = models
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _Client:
    def __init__(self, models: _Models) -> None:
        self.aio = _Aio(models)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class Rig:
    def __init__(self, outcome: object, secrets: Any = None) -> None:  # noqa: ANN401
        if secrets is None:
            secrets = InMemorySecretStore()
            secrets.set("gemini", "api_key", KEY)
        self.models = _Models(outcome)
        self.client = _Client(self.models)
        self.keys: list[str] = []
        self.provider = GeminiSummaryProvider(
            secrets, client_factory=self._factory, model="fake-model"
        )

    def _factory(self, api_key: str) -> Any:  # noqa: ANN401
        self.keys.append(api_key)
        return self.client


async def test_returns_the_parsed_summary_and_asks_for_structured_output() -> None:
    rig = Rig(GOOD.model_dump_json())
    assert await rig.provider.summarize("the prompt") == GOOD
    call = rig.models.calls[0]
    assert call["model"] == "fake-model"
    assert call["contents"] == "the prompt"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema is DailySummary
    assert rig.keys == [KEY]
    assert rig.client.aio.closed is True
    assert rig.client.closed is True


def test_name_and_default_model() -> None:
    assert Rig(None).provider.name == "gemini"
    assert DEFAULT_MODEL == "gemini-3.5-flash-lite"


async def test_missing_key_is_a_provider_error_and_no_call_is_made() -> None:
    rig = Rig(GOOD.model_dump_json(), secrets=InMemorySecretStore())
    with pytest.raises(SummaryProviderError, match="API key is not set"):
        await rig.provider.summarize("p")
    assert rig.models.calls == []


async def test_unavailable_secret_store_is_a_provider_error() -> None:
    rig = Rig(GOOD.model_dump_json(), secrets=UnavailableSecretStore())
    with pytest.raises(SummaryProviderError, match="secret store unavailable") as caught:
        await rig.provider.summarize("p")
    assert not isinstance(caught.value, SecretStoreError)


async def test_429_is_rate_limited() -> None:
    rig = Rig(
        errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})
    )
    with pytest.raises(SummaryRateLimited):
        await rig.provider.summarize("p")
    assert rig.client.aio.closed is True


@pytest.mark.parametrize("code", [401, 403])
async def test_rejected_key_message_is_fixed(code: int) -> None:
    rig = Rig(errors.ClientError(code, {"error": {"message": f"bad {KEY}", "status": "X"}}))
    with pytest.raises(SummaryProviderError, match="rejected the API key") as caught:
        await rig.provider.summarize("p")
    assert KEY not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


async def test_other_api_errors_carry_only_the_status_code() -> None:
    rig = Rig(errors.ServerError(500, {"error": {"message": "secret prompt echo", "status": "X"}}))
    with pytest.raises(SummaryProviderError) as caught:
        await rig.provider.summarize("p")
    assert str(caught.value) == "Gemini request failed (500)"


async def test_network_failure_is_a_provider_error() -> None:
    rig = Rig(httpx.ConnectError("boom with details"))
    with pytest.raises(SummaryProviderError, match="unreachable") as caught:
        await rig.provider.summarize("p")
    assert "boom" not in str(caught.value)


@pytest.mark.parametrize("text", [None, "", "not json", '{"headline": 5}', '{"x": 1}'])
async def test_malformed_output_is_a_provider_error(text: str | None) -> None:
    rig = Rig(text)
    with pytest.raises(SummaryProviderError, match="malformed"):
        await rig.provider.summarize("p")


async def test_a_non_json_http_body_is_a_provider_error_without_the_body() -> None:
    rig = Rig(errors.UnknownApiResponseError("<html>captive portal secret-page</html>"))
    with pytest.raises(SummaryProviderError, match="malformed response") as caught:
        await rig.provider.summarize("p")
    assert "portal" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert rig.client.aio.closed is True
    assert rig.client.closed is True
