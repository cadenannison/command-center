"""The stored chat settings: opt-in, provider and what context may be sent (decisions 0160-0166).

Everything here is non-secret and lives in the app-setting store; the provider's API key is a
credential in the secret store (source "chat", or the existing "gemini"). The environment values
are only the defaults for a user who never saved the setting. Chat is off, and sends no history
and no notes, until the user turns each on.
"""

import asyncio
import re

from pydantic import BaseModel, ConfigDict

from command_center.core.chat import (
    CHAT_KINDS,
    ChatKind,
    address_holds_api_key,
    model_name_looks_like_api_key,
)
from command_center.core.ports import AppSettingStore
from command_center.core.urlcheck import require_chat_base_url
from command_center.services.errors import ChatNotConfiguredError, InvalidChatSettingError

ENABLED_KEY = "chat.enabled"
KIND_KEY = "chat.kind"
BASE_URL_KEY = "chat.base_url"
MODEL_KEY = "chat.model"
HISTORY_KEY = "chat.include_history"
NOTES_KEY = "chat.include_notes"
MAX_URL_LENGTH = 300
MAX_MODEL_LENGTH = 100
_ON = "on"
_OFF = "off"
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*")
_KEY_IN_FIELD = "The {field} looks like an API key; keys go on the key card, not in this field"


class ChatDefaults(BaseModel):
    """The environment's values, used until the user saves the matching setting."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    kind: ChatKind = "gemini"
    base_url: str | None = None
    model: str | None = None


class ChatConfig(BaseModel):
    """A validated provider choice and the two context opt-ins, as read for one request."""

    model_config = ConfigDict(frozen=True)

    kind: ChatKind
    base_url: str | None
    model: str | None
    include_history: bool
    include_notes: bool


def normalise_provider(
    kind: str, base_url: str | None, model: str | None
) -> tuple[ChatKind, str | None, str | None]:
    """The provider choice cleaned and checked; InvalidChatSettingError says what is wrong.

    Gemini takes no address. A server address must pass the URL guard (`require_chat_base_url`:
    http only to localhost or the LAN, https and a public address anywhere else, metadata and
    link-local never). An OpenAI-compatible server needs an address and a model.
    """
    chosen: ChatKind | None = next((known for known in CHAT_KINDS if known == kind), None)
    if chosen is None:
        msg = "Unknown chat provider: choose gemini, ollama or openai_compatible"
        raise InvalidChatSettingError(msg)
    address = (base_url or "").strip() or None
    name = (model or "").strip() or None
    if name is not None and len(name) > MAX_MODEL_LENGTH:
        msg = f"The model name must be at most {MAX_MODEL_LENGTH} characters"
        raise InvalidChatSettingError(msg)
    if name is not None and model_name_looks_like_api_key(name):
        raise InvalidChatSettingError(_KEY_IN_FIELD.format(field="model name"))
    if name is not None and not _MODEL.fullmatch(name):
        msg = "The model name must be 1 to 100 letters, digits or . _ : / @ + -"
        raise InvalidChatSettingError(msg)
    if chosen == "gemini":
        if address is not None:
            msg = "Gemini takes no server address"
            raise InvalidChatSettingError(msg)
    elif address is not None:
        address = _checked_address(address)
    if chosen == "openai_compatible" and (address is None or name is None):
        msg = "An OpenAI-compatible server needs an address and a model name"
        raise InvalidChatSettingError(msg)
    return chosen, address, name


def _checked_address(address: str) -> str:
    if address_holds_api_key(address):
        raise InvalidChatSettingError(_KEY_IN_FIELD.format(field="server address"))
    if len(address) > MAX_URL_LENGTH:
        msg = "The server address is too long"
        raise InvalidChatSettingError(msg)
    try:
        return require_chat_base_url(address).rstrip("/")
    except ValueError:
        msg = (
            "The server address is not allowed: use http only for localhost or a LAN address, "
            "https and a public address for anything else"
        )
        raise InvalidChatSettingError(msg) from None


class ChatSettings:
    """Reads and writes the chat settings; every store call runs off the event loop."""

    def __init__(self, store: AppSettingStore, defaults: ChatDefaults | None = None) -> None:
        self._store = store
        self._defaults = defaults or ChatDefaults()
        # One reader at a time sees the provider block whole, never half of an old and a new one.
        self._provider_lock = asyncio.Lock()

    async def enabled(self) -> bool:
        """True when the user opted in (stored value), else the environment default."""
        stored = await self._get(ENABLED_KEY)
        return self._defaults.enabled if stored is None else stored == _ON

    async def config(self) -> ChatConfig:
        """The provider and opt-ins now in force; ChatNotConfiguredError if the provider is bad.

        The provider block (kind, address, model) is read from the store as a whole when the user
        saved a kind, else from the defaults, so a default address never mixes with a stored kind.
        """
        async with self._provider_lock:
            stored_kind = await self._get(KIND_KEY)
            if stored_kind is None:
                kind, base_url, model = (
                    self._defaults.kind,
                    self._defaults.base_url,
                    self._defaults.model,
                )
            else:
                kind, base_url, model = (
                    stored_kind,
                    await self._get(BASE_URL_KEY),
                    await self._get(MODEL_KEY),
                )
        try:
            chosen, address, name = normalise_provider(kind, base_url, model)
        except InvalidChatSettingError as exc:
            raise ChatNotConfiguredError(str(exc)) from None
        return ChatConfig(
            kind=chosen,
            base_url=address,
            model=name,
            include_history=await self._flag(HISTORY_KEY),
            include_notes=await self._flag(NOTES_KEY),
        )

    async def set_enabled(self, *, enabled: bool) -> None:
        """Turn chat on or off."""
        await self._set(ENABLED_KEY, _ON if enabled else _OFF)

    async def set_provider(
        self, kind: str, base_url: str | None = None, model: str | None = None
    ) -> None:
        """Choose the provider; InvalidChatSettingError for one that cannot be used.

        The three values are validated together and nothing is stored when any is refused.
        """
        chosen, address, name = normalise_provider(kind, base_url, model)
        async with self._provider_lock:
            await self._set(BASE_URL_KEY, address or "")
            await self._set(MODEL_KEY, name or "")
            await self._set(KIND_KEY, chosen)

    async def set_include_history(self, *, enabled: bool) -> None:
        """Let recently completed items into the context (off by default)."""
        await self._set(HISTORY_KEY, _ON if enabled else _OFF)

    async def set_include_notes(self, *, enabled: bool) -> None:
        """Let the user's notes into the context (off by default)."""
        await self._set(NOTES_KEY, _ON if enabled else _OFF)

    async def _flag(self, key: str) -> bool:
        return await self._get(key) == _ON

    async def _get(self, key: str) -> str | None:
        return await asyncio.to_thread(self._store.get, key)

    async def _set(self, key: str, value: str) -> None:
        await asyncio.to_thread(self._store.set, key, value)
