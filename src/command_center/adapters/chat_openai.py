"""OpenAI-compatible chat provider: llama.cpp, LM Studio, vLLM, OpenRouter and OpenAI itself.

httpx only: the wire format is a small, stable JSON shape, so no vendor SDK is imported. The key,
when the server needs one, is read from the secret store on every call and goes nowhere but the
Authorization header.
"""

import asyncio
from collections.abc import Mapping, Sequence
from typing import cast

from command_center.adapters.chat_http import checked_base_url, malformed, post_json
from command_center.core.chat import ChatMessage
from command_center.core.errors import ChatProviderError, SecretStoreError
from command_center.core.ports import SecretStore
from command_center.core.schema import ValidationResult
from command_center.core.urlcheck import may_send_key

SECRET_SOURCE = "chat"  # noqa: S105  (a source name, not a secret)
SECRET_KEY = "api_key"  # noqa: S105  (a key name, not a secret)
_NAME = "The chat server"


class OpenAICompatibleChatProvider:
    """ChatProvider over `POST {base_url}/chat/completions`."""

    def __init__(self, secrets: SecretStore, *, base_url: str, model: str) -> None:
        self._secrets = secrets
        self._base_url = base_url
        self._model = model

    @property
    def name(self) -> str:
        return "openai_compatible"

    async def complete(self, messages: Sequence[ChatMessage], system: str, max_tokens: int) -> str:
        base = await checked_base_url(self._base_url)
        headers = await self._headers(base)
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                *({"role": m.role, "content": m.content} for m in messages),
            ],
            "max_tokens": max_tokens,
            "stream": False,
        }
        body = await post_json(_NAME, f"{base}/chat/completions", payload, headers)
        return _reply(body)

    async def _headers(self, base: str) -> dict[str, str]:
        """The Authorization header for base, or none when no key is stored.

        A stored key is refused, not dropped, for an http address that is not loopback: sending
        the request without it would still send the agenda, and the user would not know why the
        server answered 401 (decision 0220).
        """
        try:
            creds = await asyncio.to_thread(self._secrets.get, SECRET_SOURCE)
        except SecretStoreError:
            msg = "secret store unavailable"
            raise ChatProviderError(msg) from None
        key = creds.get(SECRET_KEY, "").strip()
        if not key:
            return {}
        if not may_send_key(base):
            msg = "The chat server key is not sent over plain http to this address; use https"
            raise ChatProviderError(msg)
        return {"Authorization": f"Bearer {key}"}


class ChatKeyIntegration:
    """IntegrationAdapter for the OpenAI-compatible server's API key (decision 0162).

    It checks only that a key was entered: which server the key belongs to is a stored setting
    that can change, and validating against it here would send the key to an address nobody
    re-checked. The key is used, and so first sent anywhere, only when chat is on and a message
    is sent.
    """

    @property
    def name(self) -> str:
        return SECRET_SOURCE

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        """Ok for a non-blank key; it is not sent anywhere."""
        if not creds.get(SECRET_KEY, "").strip():
            return ValidationResult(ok=False, message="Enter the chat server's API key")
        return ValidationResult(ok=True, message="Stored; sent only to the configured chat server")


def _reply(body: object) -> str:
    choices = cast("dict[str, object]", body).get("choices") if isinstance(body, dict) else None
    first = cast("list[object]", choices)[0] if isinstance(choices, list) and choices else None
    message = cast("dict[str, object]", first).get("message") if isinstance(first, dict) else None
    content = (
        cast("dict[str, object]", message).get("content") if isinstance(message, dict) else None
    )
    if not isinstance(content, str):
        raise malformed(_NAME)
    return content
