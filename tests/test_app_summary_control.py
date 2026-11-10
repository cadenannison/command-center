"""build_container wires the stored summary switch: env default, UI override, restart, provider."""

from pathlib import Path

import pytest

from command_center.adapters.keyring_store import KeyringSecretStore
from command_center.app import build_container, build_summary_provider
from command_center.config import Settings


@pytest.fixture(autouse=True)
def database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'control.db'}")


def settings_with(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


async def test_by_default_there_is_a_control_and_no_service() -> None:
    container = build_container(settings_with())

    assert container.summary_control is not None
    assert container.summary is None
    assert await container.summary_service() is None


async def test_the_environment_default_enables_the_service_at_startup() -> None:
    container = build_container(settings_with(summary_enabled=True))

    assert container.summary is not None
    assert await container.summary_service() is container.summary


async def test_enabling_in_the_ui_builds_the_service_lazily_and_survives_a_restart() -> None:
    first = build_container(settings_with())
    assert first.summary_control is not None
    await first.summary_control.set_enabled(enabled=True)

    assert first.summary is None
    assert await first.summary_service() is not None

    second = build_container(settings_with())
    assert await second.summary_service() is not None


async def test_turning_it_off_in_the_ui_beats_the_environment_default() -> None:
    container = build_container(settings_with(summary_enabled=True))
    assert container.summary_control is not None

    await container.summary_control.set_enabled(enabled=False)

    assert container.summary is not None
    assert await container.summary_service() is None


async def test_the_provider_chosen_in_the_ui_beats_the_environment_default() -> None:
    container = build_container(settings_with(summary_enabled=True, summary_provider="gemini"))
    assert container.summary_control is not None

    await container.summary_control.set_provider("ollama")
    service = await container.summary_service()

    assert service is not None
    assert service.provider_name == "ollama"


async def test_a_provider_other_than_the_configured_one_gets_a_fresh_service() -> None:
    container = build_container(settings_with(summary_enabled=True))
    assert container.summary_control is not None

    await container.summary_control.set_provider("ollama")

    assert await container.summary_service() is not container.summary


@pytest.mark.parametrize("chosen", ["gemini", "ollama"])
def test_a_chosen_provider_is_built_even_when_another_is_configured(chosen: str) -> None:
    settings = settings_with(summary_provider="gemini", summary_model="fake-gemini-model")

    assert build_summary_provider(settings, KeyringSecretStore(), chosen).name == chosen
