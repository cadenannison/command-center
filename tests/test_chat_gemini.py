"""GeminiChatProvider over a fake SDK client: key from the secret store, errors translated."""

from typing import Any, cast

import httpx
import pytest
from google.genai import errors

from chat_support import FAKE_KEY
from command_center.adapters.summary_gemini import DEFAULT_MODEL, GeminiChatProvider
from command_center.core.chat import ChatMessage
from command_center.core.errors import ChatProviderError, ChatRateLimited
from fake_adapter import UnavailableSecretStore
from fakes import InMemorySecretStore

MESSAGES = [
    ChatMessage(role="user", content="hi"),
    ChatMessage(role="assistant", content="yo"),
    ChatMessage(role="user", content="and?"),
]


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
            secrets.set("gemini", "api_key", FAKE_KEY)
        self.models = _Models(outcome)
        self.client = _Client(self.models)
        self.keys: list[str] = []
        self.provider = GeminiChatProvider(
            secrets, client_factory=self._factory, model="fake-model"
        )

    def _factory(self, api_key: str) -> Any:  # noqa: ANN401
        self.keys.append(api_key)
        return self.client


async def test_sends_the_turns_with_the_system_instruction_and_returns_the_text() -> None:
    rig = Rig("the answer")

    assert await rig.provider.complete(MESSAGES, "the system", 77) == "the answer"

    call = rig.models.calls[0]
    assert call["model"] == "fake-model"
    assert [(c.role, c.parts[0].text) for c in call["contents"]] == [
        ("user", "hi"),
        ("model", "yo"),
        ("user", "and?"),
    ]
    assert call["config"].system_instruction == "the system"
    assert call["config"].max_output_tokens == 77
    assert rig.keys == [FAKE_KEY]
    assert rig.client.aio.closed is True
    assert rig.client.closed is True


def test_name_and_default_model() -> None:
    assert Rig(None).provider.name == "gemini"
    assert DEFAULT_MODEL == "gemini-3.5-flash-lite"


async def test_a_missing_key_is_a_provider_error_and_no_call_is_made() -> None:
    rig = Rig("x", secrets=InMemorySecretStore())

    with pytest.raises(ChatProviderError, match="API key is not set"):
        await rig.provider.complete(MESSAGES, "s", 9)

    assert rig.models.calls == []


async def test_an_unavailable_secret_store_is_a_provider_error() -> None:
    rig = Rig("x", secrets=UnavailableSecretStore())

    with pytest.raises(ChatProviderError, match="secret store unavailable"):
        await rig.provider.complete(MESSAGES, "s", 9)


async def test_429_is_rate_limited() -> None:
    rig = Rig(errors.ClientError(429, {"error": {"message": "quota", "status": "X"}}))

    with pytest.raises(ChatRateLimited):
        await rig.provider.complete(MESSAGES, "s", 9)

    assert rig.client.aio.closed is True


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (
            errors.ClientError(403, {"error": {"message": f"bad {FAKE_KEY}", "status": "X"}}),
            "rejected",
        ),
        (
            errors.ServerError(500, {"error": {"message": f"echo {FAKE_KEY}", "status": "X"}}),
            "(500)",
        ),
        (httpx.ConnectError("boom " + FAKE_KEY), "unreachable"),
    ],
)
async def test_failures_are_fixed_text_without_the_sdks_message(
    error: Exception, text: str
) -> None:
    rig = Rig(error)

    with pytest.raises(ChatProviderError) as caught:
        await rig.provider.complete(MESSAGES, "s", 9)

    assert text in str(caught.value)
    assert FAKE_KEY not in str(caught.value)
    assert caught.value.__context__ is None or caught.value.__suppress_context__


@pytest.mark.parametrize("text", [None, ""])
async def test_an_empty_answer_is_a_provider_error(text: str | None) -> None:
    with pytest.raises(ChatProviderError, match="no text"):
        await Rig(text).provider.complete(MESSAGES, "s", 9)
