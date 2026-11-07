"""Settings come from CC_* environment variables with safe defaults and are immutable."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from command_center.config import Settings

ENV_NAMES = [
    "CC_HOST",
    "CC_PORT",
    "CC_DATA_DIR",
    "CC_DATABASE_URL",
    "DATABASE_URL",
    "CC_TZ",
    "CC_SYNC_INTERVAL_MINUTES",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))


def make() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_defaults() -> None:
    settings = make()
    assert (settings.host, settings.port, settings.tz, settings.sync_interval_minutes) == (
        "127.0.0.1",
        8765,
        "America/Denver",
        30,
    )


def test_default_data_dir_is_under_the_home_directory(tmp_path: Path) -> None:
    assert make().data_dir == tmp_path / ".command-center"


def test_default_database_is_a_sqlite_file_under_data_dir(tmp_path: Path) -> None:
    assert make().database_url == f"sqlite:///{tmp_path / '.command-center' / 'command_center.db'}"


def test_default_database_follows_a_custom_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path / "elsewhere"))
    assert make().database_url == f"sqlite:///{tmp_path / 'elsewhere' / 'command_center.db'}"


def test_cc_database_url_overrides_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_DATABASE_URL", "postgresql+psycopg://u@h/db")
    assert make().database_url == "postgresql+psycopg://u@h/db"


def test_unprefixed_database_url_is_also_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u@h/other")
    assert make().database_url == "postgresql+psycopg://u@h/other"


def test_cc_database_url_wins_over_unprefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_DATABASE_URL", "sqlite:///a.db")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///b.db")
    assert make().database_url == "sqlite:///a.db"


def test_other_fields_are_read_from_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_PORT", "9000")
    monkeypatch.setenv("CC_TZ", "Europe/Paris")
    monkeypatch.setenv("CC_SYNC_INTERVAL_MINUTES", "5")
    settings = make()
    assert (settings.port, settings.tz, settings.sync_interval_minutes) == (9000, "Europe/Paris", 5)


def test_settings_are_immutable() -> None:
    with pytest.raises(ValidationError):
        make().port = 1  # type: ignore[misc]


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "localhost"])  # noqa: S104
def test_non_loopback_host_is_rejected(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("CC_HOST", host)
    with pytest.raises(ValidationError):
        make()


@pytest.mark.parametrize("port", ["0", "65536", "-1", "abc"])
def test_invalid_port_is_rejected(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("CC_PORT", port)
    with pytest.raises(ValidationError):
        make()


def test_unknown_timezone_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_TZ", "Mars/Olympus")
    with pytest.raises(ValidationError, match="Unknown timezone"):
        make()


@pytest.mark.parametrize("minutes", ["0", "-5"])
def test_non_positive_sync_interval_is_rejected(
    monkeypatch: pytest.MonkeyPatch, minutes: str
) -> None:
    monkeypatch.setenv("CC_SYNC_INTERVAL_MINUTES", minutes)
    with pytest.raises(ValidationError):
        make()


def test_repr_does_not_reveal_database_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:fake-hunter2pw@host/db")
    settings = make()
    assert "fake-hunter2pw" not in repr(settings)
    assert "fake-hunter2pw" not in str(settings)
