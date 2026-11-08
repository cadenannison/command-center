"""Gemini summary provider. The only importer of google-genai (docs/MAP.md).

Failures become core.errors.SummaryProviderError / SummaryRateLimited. Their messages are fixed
text: never the API key, the prompt or the SDK's own message.
"""

import asyncio
from collections.abc import Callable, Mapping

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from command_center.core.errors import (
    SecretStoreError,
    SummaryProviderError,
    SummaryRateLimited,
    TransientError,
)
from command_center.core.ports import SecretStore
from command_center.core.schema import ValidationResult
from command_center.core.summary import DailySummary

DEFAULT_MODEL = "gemini-3.5-flash-lite"
SECRET_SOURCE = "gemini"  # noqa: S105  (a source name, not a secret)
SECRET_KEY = "api_key"  # noqa: S105  (a key name, not a secret)
VALIDATE_TIMEOUT_SECONDS = 15.0
_TIMEOUT_MS = 30_000
_RATE_LIMITED = 429
_REJECTED_KEY = frozenset({401, 403})
# Google answers an unknown key with 400 (API_KEY_INVALID), so validation also reads 400 as a
# rejected key; a generation request that fails with 400 stays "request failed".
_VALIDATION_REJECTED = frozenset({400, *_REJECTED_KEY})
_SERVER_ERROR = 500


def _default_client(api_key: str, *, timeout_ms: int = _TIMEOUT_MS) -> genai.Client:
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))


def _validation_client(api_key: str) -> genai.Client:
    return _default_client(api_key, timeout_ms=int(VALIDATE_TIMEOUT_SECONDS * 1000))


class GeminiSummaryProvider:
    """SummaryProvider over the Gemini API with structured output (the DailySummary schema)."""

    def __init__(
        self,
        secrets: SecretStore,
        *,
        model: str = DEFAULT_MODEL,
        client_factory: Callable[[str], genai.Client] = _default_client,
    ) -> None:
        self._secrets = secrets
        self._model = model
        self._client_factory = client_factory

    @property
    def name(self) -> str:
        return "gemini"

    async def summarize(self, prompt: str) -> DailySummary:
        api_key = await self._api_key()
        client = self._client_factory(api_key)
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DailySummary,
        )
        try:
            response = await client.aio.models.generate_content(  # pyright: ignore[reportUnknownMemberType]  (SDK's own partly-unknown overloads)
                model=self._model, contents=prompt, config=config
            )
        except errors.APIError as exc:
            raise _translate(exc.code) from None
        except errors.UnknownApiResponseError:
            # Not an APIError: a body that is not JSON (a proxy page, a cut-off reply). The SDK's
            # own message embeds the raw body, so it is dropped.
            msg = "Gemini returned a malformed response"
            raise SummaryProviderError(msg) from None
        except httpx.HTTPError:
            msg = "Gemini is unreachable"
            raise SummaryProviderError(msg) from None
        finally:
            await client.aio.aclose()
            client.close()
        return _parse(response.text)

    async def _api_key(self) -> str:
        try:
            creds = await asyncio.to_thread(self._secrets.get, SECRET_SOURCE)
        except SecretStoreError:
            msg = "secret store unavailable"
            raise SummaryProviderError(msg) from None
        key = creds.get(SECRET_KEY)
        if not key:
            msg = "Gemini API key is not set"
            raise SummaryProviderError(msg)
        return key


def _translate(code: int) -> SummaryProviderError:
    if code == _RATE_LIMITED:
        return SummaryRateLimited("Gemini rate limit or quota reached")
    if code in _REJECTED_KEY:
        return SummaryProviderError("Gemini rejected the API key")
    return SummaryProviderError(f"Gemini request failed ({code})")


def _parse(text: str | None) -> DailySummary:
    try:
        return DailySummary.model_validate_json(text or "")
    except ValidationError:
        msg = "Gemini returned a malformed summary"
        raise SummaryProviderError(msg) from None


class GeminiIntegration:
    """IntegrationAdapter for the Gemini API key: validates it with one cheap token count.

    Messages are fixed text, like the provider's: never the key or the SDK's message.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        client_factory: Callable[[str], genai.Client] = _validation_client,
        timeout: float = VALIDATE_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model
        self._client_factory = client_factory
        self._timeout = timeout

    @property
    def name(self) -> str:
        return SECRET_SOURCE

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        """Ok if Gemini accepts the key; a rejected one is `ok=False`, an outage is transient."""
        api_key = creds.get(SECRET_KEY, "").strip()
        if not api_key:
            return ValidationResult(ok=False, message="Enter a Gemini API key")
        client = self._client_factory(api_key)
        try:
            async with asyncio.timeout(self._timeout):
                await client.aio.models.count_tokens(model=self._model, contents="ping")  # pyright: ignore[reportUnknownMemberType]  (SDK's own partly-unknown overloads)
        except errors.APIError as exc:
            failure = _validation_failure(exc.code)
            if isinstance(failure, TransientError):
                raise failure from None
            return failure
        except TimeoutError:
            msg = "Gemini did not answer in time"
            raise TransientError(msg) from None
        except errors.UnknownApiResponseError:
            msg = "Gemini returned a malformed response"
            raise TransientError(msg) from None
        except httpx.HTTPError:
            msg = "Gemini is unreachable"
            raise TransientError(msg) from None
        finally:
            await client.aio.aclose()
            client.close()
        return ValidationResult(ok=True, message="Gemini accepted the API key")


def _validation_failure(code: int) -> ValidationResult | TransientError:
    if code in _VALIDATION_REJECTED:
        return ValidationResult(ok=False, message="Gemini rejected the API key")
    if code == _RATE_LIMITED:
        return TransientError("Gemini rate limit or quota reached")
    if code >= _SERVER_ERROR:
        return TransientError("Gemini is down")
    return ValidationResult(ok=False, message=f"Gemini request failed ({code})")
