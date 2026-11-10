"""The stored chat settings: defaults, the provider block, and the URL guard on every address."""

import pytest

from command_center.services.chat_settings import (
    BASE_URL_KEY,
    KIND_KEY,
    ChatDefaults,
    ChatSettings,
    normalise_provider,
)
from command_center.services.errors import ChatNotConfiguredError, InvalidChatSettingError
from fakes import InMemoryAppSettingStore


def settings(defaults: ChatDefaults | None = None) -> tuple[ChatSettings, InMemoryAppSettingStore]:
    store = InMemoryAppSettingStore()
    return ChatSettings(store, defaults), store


async def test_chat_is_off_and_sends_no_history_or_notes_by_default() -> None:
    chat, _ = settings()

    config = await chat.config()

    assert await chat.enabled() is False
    assert (config.include_history, config.include_notes) == (False, False)
    assert config.kind == "gemini"


async def test_the_environment_values_are_the_defaults() -> None:
    chat, _ = settings(
        ChatDefaults(
            enabled=True,
            kind="openai_compatible",
            base_url="http://192.168.1.20:8080/v1",
            model="fake-model",
        )
    )

    config = await chat.config()

    assert await chat.enabled() is True
    assert (config.kind, config.base_url, config.model) == (
        "openai_compatible",
        "http://192.168.1.20:8080/v1",
        "fake-model",
    )


async def test_a_stored_value_beats_the_environment_and_the_provider_block_is_whole() -> None:
    chat, _ = settings(ChatDefaults(enabled=True, kind="ollama", base_url="http://localhost:1/"))

    await chat.set_enabled(enabled=False)
    await chat.set_provider("gemini")
    config = await chat.config()

    assert await chat.enabled() is False
    # the environment's address does not leak into a provider the user saved
    assert (config.kind, config.base_url) == ("gemini", None)


async def test_each_context_opt_in_is_its_own_switch() -> None:
    chat, _ = settings()

    await chat.set_include_notes(enabled=True)
    assert (await chat.config()).include_notes is True
    assert (await chat.config()).include_history is False

    await chat.set_include_notes(enabled=False)
    await chat.set_include_history(enabled=True)
    assert (await chat.config()).include_notes is False
    assert (await chat.config()).include_history is True


@pytest.mark.parametrize(
    "address",
    [
        "http://localhost:11434",
        "http://127.0.0.1:1234/v1",
        "http://192.168.1.20:8080/v1",
        "http://10.0.0.5",
        "http://gpu-box:8000",
        "https://api.openai.com/v1",
        "https://openrouter.ai/api/v1",
    ],
)
def test_an_address_the_guard_allows_is_accepted(address: str) -> None:
    assert normalise_provider("openai_compatible", address, "fake-model")[1] == address


@pytest.mark.parametrize(
    "address",
    [
        "http://api.openai.com/v1",  # a public host over http
        "http://8.8.8.8",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata, over http
        "https://169.254.169.254/",  # and over https
        "http://[fe80::1]:8000",  # link-local
        "http://metadata.google.internal/",
        "http://100.64.0.1",  # CGNAT is not LAN
        "ftp://localhost",
        "http://user:fake-pass@localhost:1234",  # credentials in the address
        "http://localhost:1234/v1?key=fake-key",  # a key in the address
        "localhost:1234",  # no scheme
        "http://",
    ],
)
def test_an_address_the_guard_refuses_is_refused_without_echoing_it(address: str) -> None:
    with pytest.raises(InvalidChatSettingError) as caught:
        normalise_provider("openai_compatible", address, "fake-model")
    for part in ("fake-pass", "fake-key", "169.254", "metadata", "user:"):
        assert part not in str(caught.value)


@pytest.mark.parametrize(
    ("kind", "address", "model"),
    [
        ("claude", None, None),  # unknown provider
        ("gemini", "http://localhost:1", None),  # Gemini takes no address
        ("openai_compatible", None, "fake-model"),  # needs an address
        ("openai_compatible", "http://localhost:1", None),  # and a model
        ("ollama", None, "bad model name"),
        ("ollama", None, "x" * 101),
        ("ollama", "http://localhost:" + "1" * 300, None),
    ],
)
def test_an_unusable_provider_is_refused(kind: str, address: str | None, model: str | None) -> None:
    with pytest.raises(InvalidChatSettingError):
        normalise_provider(kind, address, model)


async def test_a_refused_provider_stores_nothing() -> None:
    chat, store = settings()

    with pytest.raises(InvalidChatSettingError):
        await chat.set_provider("ollama", "http://169.254.169.254", "fake-model")

    assert store.get(KIND_KEY) is None
    assert store.get(BASE_URL_KEY) is None


async def test_a_stored_address_that_is_no_longer_allowed_is_not_used() -> None:
    chat, store = settings()
    store.set(KIND_KEY, "ollama")
    store.set(BASE_URL_KEY, "http://169.254.169.254/")  # written behind the service's back

    with pytest.raises(ChatNotConfiguredError) as caught:
        await chat.config()

    assert "169.254" not in str(caught.value)
