"""Ollama summary provider: the local option, nothing leaves the machine.

Talks to a fixed local endpoint over httpx in JSON mode. Failures become
core.errors.SummaryProviderError / SummaryRateLimited with fixed messages.
"""

import logging
from typing import cast

import httpx
from pydantic import ValidationError

from command_center.core.errors import SummaryProviderError, SummaryRateLimited
from command_center.core.summary import DailySummary

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"
# A local model on a laptop can take a while; a hung server must still end.
_TIMEOUT_SECONDS = 120.0
_BUSY = frozenset({429, 503})
_NOT_FOUND = 404
_ERROR_STATUS = 400


class OllamaSummaryProvider:
    """SummaryProvider over Ollama's /api/generate with format=json."""

    def __init__(self, *, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "ollama"

    async def summarize(self, prompt: str) -> DailySummary:
        payload = {"model": self._model, "prompt": prompt, "format": "json", "stream": False}
        try:
            # trust_env=False: a proxy in the environment must not carry the prompt (0246).
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, trust_env=False) as client:
                response = await client.post(f"{self._base_url}/api/generate", json=payload)
        except httpx.TimeoutException:
            msg = "Ollama timed out"
            raise SummaryProviderError(msg) from None
        except httpx.HTTPError:
            msg = "Ollama is unreachable; is it running?"
            raise SummaryProviderError(msg) from None
        except Exception as exc:  # noqa: BLE001  (a library's own text can hold the prompt)
            logger.warning(
                "Ollama summary request failed",
                extra={"reason": "ollama_summary_failed", "error_class": type(exc).__name__},
            )
            msg = "Ollama request failed"
            raise SummaryProviderError(msg) from None
        _check_status(response)
        return _parse(response)


def _check_status(response: httpx.Response) -> None:
    status = response.status_code
    if status in _BUSY:
        msg = "Ollama is busy"
        raise SummaryRateLimited(msg)
    if status == _NOT_FOUND:
        msg = "Ollama does not have that model; pull it first"
        raise SummaryProviderError(msg)
    if status >= _ERROR_STATUS:
        msg = f"Ollama request failed ({status})"
        raise SummaryProviderError(msg)


def _malformed() -> SummaryProviderError:
    return SummaryProviderError("Ollama returned a malformed summary")


def _parse(response: httpx.Response) -> DailySummary:
    try:
        body: object = response.json()
    except ValueError:
        raise _malformed() from None
    text = cast("dict[str, object]", body).get("response") if isinstance(body, dict) else None
    if not isinstance(text, str):
        raise _malformed()
    try:
        return DailySummary.model_validate_json(text)
    except ValidationError:
        raise _malformed() from None
