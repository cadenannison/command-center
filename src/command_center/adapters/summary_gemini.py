"""Gemini summary provider. The only importer of google-genai (docs/MAP.md).

Failures become core.errors.SummaryProviderError / SummaryRateLimited. Their messages are fixed
text: never the API key, the prompt or the SDK's own message.
"""

import asyncio
from collections.abc import Callable

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from command_center.core.errors import SecretStoreError, SummaryProviderError, SummaryRateLimited
from command_center.core.ports import SecretStore
from command_center.core.summary import DailySummary

DEFAULT_MODEL = "gemini-3.5-flash-lite"
SECRET_SOURCE = "gemini"  # noqa: S105  (a source name, not a secret)
SECRET_KEY = "api_key"  # noqa: S105  (a key name, not a secret)
_TIMEOUT_MS = 30_000
_RATE_LIMITED = 429
_REJECTED_KEY = frozenset({401, 403})


def _default_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=_TIMEOUT_MS))


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
