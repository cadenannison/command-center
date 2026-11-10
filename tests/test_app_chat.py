"""The production wiring of chat: off by default, built lazily, the key entry always listed."""

from pathlib import Path

import pytest

from chat_support import FakeChatProvider
from command_center.adapters.chat_ollama import OllamaChatProvider
from command_center.adapters.chat_openai import OpenAICompatibleChatProvider
from command_center.adapters.summary_gemini import GeminiChatProvider
from command_center.app import build_chat_provider, build_container, build_integrations
from command_center.config import Settings
from command_center.core.ports import ChatProvider, SecretStore
from command_center.services.chat_settings import ChatConfig
from command_center.services.errors import ChatDisabledError
from fakes import InMemorySecretStore


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'chat.db'}")
    for name in ("ENABLED", "PROVIDER", "BASE_URL", "MODEL"):
        monkeypatch.delenv(f"CC_CHAT_{name}", raising=False)
    return tmp_path


def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def config(kind: str, base_url: str | None = None, model: str | None = None) -> ChatConfig:
    return ChatConfig.model_validate(
        {
            "kind": kind,
            "base_url": base_url,
            "model": model,
            "include_history": False,
            "include_notes": False,
        }
    )


async def test_chat_is_off_by_default_and_the_provider_is_never_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[object] = []

    def record(*args: object) -> None:
        built.append(args)

    monkeypatch.setattr("command_center.app.build_chat_provider", record)
    container = build_container(settings())
    assert container.chat is not None

    with pytest.raises(ChatDisabledError):
        await container.chat.reply("hello")

    assert built == []


def test_the_chat_key_is_a_listed_integration_even_while_chat_is_off() -> None:
    integrations = build_integrations(settings())

    assert set(integrations) == {"gemini", "chat"}
    assert type(integrations["chat"]).__name__ == "ChatKeyIntegration"


async def test_the_environment_defaults_reach_the_stored_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CC_CHAT_ENABLED", "true")
    monkeypatch.setenv("CC_CHAT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CC_CHAT_BASE_URL", "http://192.168.1.20:8080/v1")
    monkeypatch.setenv("CC_CHAT_MODEL", "fake-model")
    asked: list[ChatConfig] = []

    def record(_secrets: SecretStore, config: ChatConfig) -> ChatProvider:
        asked.append(config)
        return FakeChatProvider()

    monkeypatch.setattr("command_center.app.build_chat_provider", record)
    container = build_container(settings())
    assert container.chat is not None

    preview = await container.chat.context_preview()
    _ = await container.chat.reply("hello")

    assert preview.enabled is True
    assert [(c.kind, c.base_url, c.model) for c in asked] == [
        ("openai_compatible", "http://192.168.1.20:8080/v1", "fake-model")
    ]


def test_each_kind_builds_its_provider() -> None:
    secrets = InMemorySecretStore()

    assert isinstance(build_chat_provider(secrets, config("gemini")), GeminiChatProvider)
    assert isinstance(build_chat_provider(secrets, config("ollama")), OllamaChatProvider)
    assert isinstance(
        build_chat_provider(secrets, config("openai_compatible", "http://localhost:1/v1", "m")),
        OpenAICompatibleChatProvider,
    )


def test_the_chat_address_is_not_in_the_settings_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CC_CHAT_BASE_URL", "http://192.168.1.20:8080/v1")

    assert "192.168" not in repr(settings())
