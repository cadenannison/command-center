"""Ollama chat provider: the local option. httpx only; no vendor SDK."""

from collections.abc import Sequence
from typing import cast

from command_center.adapters.chat_http import checked_base_url, malformed, post_json
from command_center.core.chat import ChatMessage

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"
_NAME = "Ollama"


class OllamaChatProvider:
    """ChatProvider over Ollama's /api/chat (non-streaming)."""

    def __init__(self, *, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL) -> None:
        self._base_url = base_url
        self._model = model

    @property
    def name(self) -> str:
        return "ollama"

    async def complete(self, messages: Sequence[ChatMessage], system: str, max_tokens: int) -> str:
        base = await checked_base_url(self._base_url)
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                *({"role": m.role, "content": m.content} for m in messages),
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        body = await post_json(_NAME, f"{base}/api/chat", payload, {})
        return _reply(body)


def _reply(body: object) -> str:
    message = cast("dict[str, object]", body).get("message") if isinstance(body, dict) else None
    content = (
        cast("dict[str, object]", message).get("content") if isinstance(message, dict) else None
    )
    if not isinstance(content, str):
        raise malformed(_NAME)
    return content
