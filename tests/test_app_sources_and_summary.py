"""build_container registers the five sources and builds the summary only when it is enabled."""

from pathlib import Path

import pytest

from command_center.adapters.keyring_store import KeyringSecretStore
from command_center.app import build_container, build_summary_provider
from command_center.config import Settings


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'sources.db'}")


def settings_with(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


@pytest.mark.usefixtures("database")
def test_the_five_sources_are_registered_under_their_own_names() -> None:
    container = build_container(settings_with())

    assert container.sync.sources() == [
        "canvas",
        "apple_calendar",
        "learningsuite",
        "gmail",
        "weather",
    ]


@pytest.mark.usefixtures("database")
def test_summaries_are_off_by_default() -> None:
    assert build_container(settings_with()).summary is None


@pytest.mark.usefixtures("database")
@pytest.mark.parametrize("provider", ["gemini", "ollama"])
def test_summaries_are_built_when_enabled(provider: str) -> None:
    container = build_container(settings_with(summary_enabled=True, summary_provider=provider))

    assert container.summary is not None


@pytest.mark.parametrize("provider", ["gemini", "ollama"])
def test_the_configured_provider_is_the_one_built(provider: str) -> None:
    settings = settings_with(summary_enabled=True, summary_provider=provider)

    assert build_summary_provider(settings, KeyringSecretStore()).name == provider


@pytest.mark.parametrize("provider", ["gemini", "ollama"])
def test_a_configured_model_is_accepted_by_either_provider(provider: str) -> None:
    settings = settings_with(
        summary_enabled=True, summary_provider=provider, summary_model="fake-model"
    )

    assert build_summary_provider(settings, KeyringSecretStore()).name == provider
