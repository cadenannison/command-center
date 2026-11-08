"""Summary settings: opt-in, off by default, and read from CC_SUMMARY_* variables."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from command_center.config import Settings

NAMES = [
    "CC_SUMMARY_ENABLED",
    "CC_SUMMARY_PROVIDER",
    "CC_SUMMARY_MODEL",
    "CC_SUMMARY_INCLUDE_EMAIL",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))


def make() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_summaries_are_off_by_default() -> None:
    settings = make()
    assert settings.summary_enabled is False
    assert settings.summary_include_email is False


def test_default_provider_is_gemini_with_the_adapters_default_model() -> None:
    settings = make()
    assert (settings.summary_provider, settings.summary_model) == ("gemini", None)


def test_summary_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_SUMMARY_ENABLED", "true")
    monkeypatch.setenv("CC_SUMMARY_PROVIDER", "ollama")
    monkeypatch.setenv("CC_SUMMARY_MODEL", "llama3.2")
    monkeypatch.setenv("CC_SUMMARY_INCLUDE_EMAIL", "true")
    settings = make()
    assert settings.summary_enabled is True
    assert settings.summary_provider == "ollama"
    assert settings.summary_model == "llama3.2"
    assert settings.summary_include_email is True


def test_unknown_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_SUMMARY_PROVIDER", "openai")
    with pytest.raises(ValidationError):
        make()
