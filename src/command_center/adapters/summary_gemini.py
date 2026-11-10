"""Gemini summary provider. The only importer of google-genai (docs/MAP.md).

Failures become core.errors.SummaryProviderError / SummaryRateLimited. Their messages are fixed
text: never the API key, the prompt or the SDK's own message.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from command_center.core.chat import ChatMessage
from command_center.core.errors import (
    ChatProviderError,
    ChatRateLimited,
    SecretStoreError,
    SummaryProviderError,
    SummaryRateLimited,
    TransientError,
)
from command_center.core.ports import SecretStore
from command_center.core.schema import ValidationResult
from command_center.core.summary import DailySummary

logger = logging.getLogger(__name__)

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
    # trust_env=False: the SDK's httpx clients would otherwise read HTTP_PROXY and the system proxy
    # and send the key and the prompt through it (decision 0246). The timeout stays per request.
    no_env: dict[str, Any] = {"trust_env": False}
    options = types.HttpOptions(timeout=timeout_ms, client_args=no_env, async_client_args=no_env)
    return genai.Client(api_key=api_key, http_options=options)


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
        try:
            client = self._client_factory(api_key)
        except Exception as exc:  # noqa: BLE001  (the SDK's own text can hold the key)
            raise _summary_failed(exc) from None
        try:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DailySummary,
            )
            response = await client.aio.models.generate_content(  # pyright: ignore[reportUnknownMemberType]  (SDK's own partly-unknown overloads)
                model=self._model, contents=prompt, config=config
            )
            text = response.text
        except errors.APIError as exc:
            raise _translate(exc.code) from None
        except errors.UnknownApiResponseError:
            # Not an APIError: a body that is not JSON (a proxy page, a cut-off reply). The SDK's
            # own message embeds the raw body, so it is dropped.
            msg = "Gemini returned a malformed response"
            raise SummaryProviderError(msg) from None
        except Exception as exc:  # noqa: BLE001  (the SDK's own text can hold the key or the prompt)
            if _is_http_error(exc):
                msg = "Gemini is unreachable"
                raise SummaryProviderError(msg) from None
            raise _summary_failed(exc) from None
        finally:
            await _close(client)
        return _parse(text)

    async def _api_key(self) -> str:
        return await _read_key(self._secrets, SummaryProviderError)


async def _read_key(secrets: SecretStore, fail: type[Exception]) -> str:
    """The stored Gemini key; `fail` (a provider error class) is raised with fixed text."""
    try:
        creds = await asyncio.to_thread(secrets.get, SECRET_SOURCE)
    except SecretStoreError:
        msg = "secret store unavailable"
        raise fail(msg) from None
    key = creds.get(SECRET_KEY)
    if not key:
        msg = "Gemini API key is not set"
        raise fail(msg)
    return key


def _is_http_error(exc: BaseException) -> bool:
    """A network failure from the SDK's HTTP layer, whichever library it runs on.

    The SDK defaults to httpx2, whose `HTTPError` is not a subclass of httpx's, and falls back to
    httpx or aiohttp. The class is matched by name so this module needs no httpx2 dependency
    (decision 0245).
    """
    return any(
        cls.__name__ == "HTTPError" and cls.__module__.split(".")[0] in {"httpx", "httpx2"}
        for cls in type(exc).__mro__
    )


def _summary_failed(exc: Exception) -> SummaryProviderError:
    """Fixed text for an exception nothing above recognised; only its class name is logged."""
    logger.warning(
        "Gemini summary request failed",
        extra={"reason": "gemini_summary_failed", "error_class": type(exc).__name__},
    )
    return SummaryProviderError("Gemini request failed")


def _translate(code: int) -> SummaryProviderError:
    if code == _RATE_LIMITED:
        return SummaryRateLimited("Gemini rate limit or quota reached")
    if code in _REJECTED_KEY:
        return SummaryProviderError("Gemini rejected the API key")
    return SummaryProviderError(f"Gemini request failed ({code})")


class GeminiChatProvider:
    """ChatProvider over the Gemini API: the system prompt is the system instruction.

    The key is read on every call, like the summary provider's. Failures are fixed text.
    """

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

    async def complete(self, messages: Sequence[ChatMessage], system: str, max_tokens: int) -> str:
        key = await _read_key(self._secrets, ChatProviderError)
        try:
            client = self._client_factory(key)
        except Exception:  # noqa: BLE001  (the SDK's own text can hold the key or the prompt)
            raise _failed() from None
        try:
            contents = [
                types.Content(
                    role="user" if message.role == "user" else "model",
                    parts=[types.Part(text=message.content)],
                )
                for message in messages
            ]
            config = types.GenerateContentConfig(
                system_instruction=system, max_output_tokens=max_tokens
            )
            response = await client.aio.models.generate_content(  # pyright: ignore[reportUnknownMemberType]  (SDK's own partly-unknown overloads)
                model=self._model, contents=contents, config=config
            )
            text = response.text
        except errors.APIError as exc:
            raise _translate_chat(exc.code) from None
        except errors.UnknownApiResponseError:
            msg = "Gemini returned a malformed response"
            raise ChatProviderError(msg) from None
        except Exception as exc:  # noqa: BLE001  (the SDK's own text can hold the system prompt)
            if _is_http_error(exc):
                msg = "Gemini is unreachable"
                raise ChatProviderError(msg) from None
            raise _failed() from None
        finally:
            await _close(client)
        if not text:
            msg = "Gemini returned no text"
            raise ChatProviderError(msg)
        return text


def _failed() -> ChatProviderError:
    return ChatProviderError("Gemini request failed")


async def _close(client: genai.Client) -> None:
    """Close the SDK client. A failure here is logged by class and never replaces the outcome."""
    try:
        await client.aio.aclose()
    except Exception as exc:  # noqa: BLE001
        _log_cleanup_failure(exc)
    try:
        client.close()
    except Exception as exc:  # noqa: BLE001
        _log_cleanup_failure(exc)


def _log_cleanup_failure(exc: Exception) -> None:
    logger.warning(
        "Gemini client cleanup failed",
        extra={"reason": "gemini_cleanup", "error_class": type(exc).__name__},
    )


def _translate_chat(code: int) -> ChatProviderError:
    if code == _RATE_LIMITED:
        return ChatRateLimited("Gemini rate limit or quota reached")
    if code in _REJECTED_KEY:
        return ChatProviderError("Gemini rejected the API key")
    return ChatProviderError(f"Gemini request failed ({code})")


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
        except Exception as exc:
            if _is_http_error(exc):
                msg = "Gemini is unreachable"
                raise TransientError(msg) from None
            raise
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
