"""GeminiIntegration: one cheap call validates the key; fixed-text failures, no key leaks."""

import asyncio
import logging
from typing import Any

import httpx
import pytest
from google.genai import errors

from command_center.adapters.summary_gemini import (
    VALIDATE_TIMEOUT_SECONDS,
    GeminiIntegration,
)
from command_center.core.errors import TransientError

KEY = "fake-gemini-key-ABCD1234"


class _Models:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def count_tokens(self, **kwargs: Any) -> object:  # noqa: ANN401
        self.calls.append(kwargs)
        if isinstance(self._outcome, asyncio.Event):
            await self._outcome.wait()
        elif isinstance(self._outcome, BaseException):
            raise self._outcome
        return object()


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
    def __init__(self, outcome: object = None, *, timeout: float = 1.0) -> None:
        self.models = _Models(outcome)
        self.client = _Client(self.models)
        self.keys: list[str] = []
        self.integration = GeminiIntegration(
            model="fake-model", client_factory=self._factory, timeout=timeout
        )

    def _factory(self, api_key: str) -> Any:  # noqa: ANN401
        self.keys.append(api_key)
        return self.client


def api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"message": f"raw sdk text with {KEY}"}})


def test_it_is_named_gemini_so_it_shares_the_summarys_secret_source() -> None:
    assert GeminiIntegration().name == "gemini"


def test_the_default_timeout_is_15_seconds() -> None:
    assert VALIDATE_TIMEOUT_SECONDS == 15.0


async def test_an_accepted_key_is_ok_after_one_token_count_on_the_configured_model() -> None:
    rig = Rig()

    result = await rig.integration.validate({"api_key": f"  {KEY}  "})

    assert result.ok is True
    assert rig.keys == [KEY]
    assert [(c["model"], c["contents"]) for c in rig.models.calls] == [("fake-model", "ping")]
    assert rig.client.aio.closed is True
    assert rig.client.closed is True


@pytest.mark.parametrize("creds", [{}, {"api_key": ""}, {"api_key": "   "}, {"other": KEY}])
async def test_a_missing_key_is_not_ok_and_calls_nothing(creds: dict[str, str]) -> None:
    rig = Rig()

    result = await rig.integration.validate(creds)

    assert result.ok is False
    assert rig.keys == []
    assert rig.models.calls == []


@pytest.mark.parametrize("code", [400, 401, 403])
async def test_a_rejected_key_is_not_ok_with_fixed_text(code: int) -> None:
    rig = Rig(api_error(code))

    result = await rig.integration.validate({"api_key": KEY})

    assert (result.ok, result.message) == (False, "Gemini rejected the API key")
    assert KEY not in repr(result)
    assert rig.client.aio.closed is True


async def test_another_client_error_is_not_ok_and_names_only_the_code() -> None:
    result = await Rig(api_error(404)).integration.validate({"api_key": KEY})

    assert (result.ok, result.message) == (False, "Gemini request failed (404)")


@pytest.mark.parametrize("code", [429, 500, 503])
async def test_quota_and_outages_are_transient_with_fixed_text(code: int) -> None:
    rig = Rig(api_error(code))

    with pytest.raises(TransientError) as caught:
        await rig.integration.validate({"api_key": KEY})

    assert KEY not in str(caught.value)
    assert "raw sdk text" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    assert rig.client.aio.closed is True


async def test_a_network_failure_is_transient_and_does_not_chain_the_cause() -> None:
    rig = Rig(httpx.ConnectError(f"cannot connect for {KEY}"))

    with pytest.raises(TransientError) as caught:
        await rig.integration.validate({"api_key": KEY})

    assert (str(caught.value), caught.value.__cause__) == ("Gemini is unreachable", None)


async def test_a_reply_that_is_not_json_is_transient_without_the_body() -> None:
    body = f"<html>proxy page for {KEY}</html>"
    rig = Rig(errors.UnknownApiResponseError(body))

    with pytest.raises(TransientError) as caught:
        await rig.integration.validate({"api_key": KEY})

    assert str(caught.value) == "Gemini returned a malformed response"


async def test_a_call_that_never_answers_gives_up_at_the_timeout() -> None:
    rig = Rig(asyncio.Event(), timeout=0.01)

    with pytest.raises(TransientError, match="did not answer in time"):
        await rig.integration.validate({"api_key": KEY})

    assert rig.client.aio.closed is True


async def test_nothing_is_logged_while_validating(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        await Rig().integration.validate({"api_key": KEY})
        await Rig(api_error(403)).integration.validate({"api_key": KEY})

    assert KEY not in caplog.text
