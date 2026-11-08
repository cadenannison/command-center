"""The production container registers the Gemini key as a credential-only integration."""

from pathlib import Path

import pytest

from command_center.adapters.summary_gemini import DEFAULT_MODEL, GeminiIntegration
from command_center.app import build_container, build_integrations
from command_center.config import Settings
from command_center.web.sources import SOURCE_FORMS


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'integrations.db'}")
    monkeypatch.delenv("CC_SUMMARY_PROVIDER", raising=False)
    monkeypatch.delenv("CC_SUMMARY_MODEL", raising=False)
    return Settings(_env_file=None)  # type: ignore[call-arg]


async def test_the_container_lists_gemini_in_settings_but_not_in_sync(settings: Settings) -> None:
    container = build_container(settings)

    listed = [item.source for item in await container.settings.status()]

    assert listed == ["canvas", "apple_calendar", "learningsuite", "gmail", "weather", "gemini"]
    assert "gemini" not in container.sync.sources()


async def test_the_default_container_still_has_no_summary_with_the_key_entry_in_place(
    settings: Settings,
) -> None:
    assert build_container(settings).summary is None


def test_the_web_form_of_every_integration_is_credential_only(settings: Settings) -> None:
    assert set(build_integrations(settings)) == {"gemini"}
    assert SOURCE_FORMS["gemini"].credential_only is True
    assert [name for name, form in SOURCE_FORMS.items() if form.credential_only] == ["gemini"]


def test_the_gemini_integration_is_the_adapters_class(settings: Settings) -> None:
    assert isinstance(build_integrations(settings)["gemini"], GeminiIntegration)


def test_an_ollama_model_name_is_not_used_to_validate_a_gemini_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CC_SUMMARY_PROVIDER", "ollama")
    monkeypatch.setenv("CC_SUMMARY_MODEL", "llama3.2")

    integration = build_integrations(Settings(_env_file=None))["gemini"]  # type: ignore[call-arg]

    assert vars(integration)["_model"] == DEFAULT_MODEL
