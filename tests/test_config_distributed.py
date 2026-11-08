"""Distributed-mode settings: the bind opt-in, the redis requirement and the secret backend."""

import pytest
from pydantic import ValidationError

from command_center.config import Settings


def make(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key in ("CC_BIND_ALL", "CC_MODE", "CC_REDIS_URL", "CC_SECRET_BACKEND", "CC_HOST"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_the_defaults_are_single_mode_loopback_and_the_keychain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make(monkeypatch)
    assert (settings.mode, settings.secret_backend, settings.bind_all) == (
        "single",
        "keyring",
        False,
    )
    assert settings.listen_host == "127.0.0.1"


def test_bind_all_is_the_only_way_to_listen_beyond_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make(monkeypatch, CC_BIND_ALL="1")
    assert settings.listen_host == "0.0.0.0"  # noqa: S104
    assert settings.host == "127.0.0.1"


def test_cc_host_still_cannot_widen_the_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        make(monkeypatch, CC_HOST="0.0.0.0")  # noqa: S104


def test_distributed_mode_without_a_redis_url_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError, match="CC_REDIS_URL"):
        make(monkeypatch, CC_MODE="distributed")


def test_the_redis_url_is_not_shown_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make(
        monkeypatch, CC_MODE="distributed", CC_REDIS_URL="redis://:fake-hunter2pw@redis:6379/0"
    )
    assert "fake-hunter2pw" not in repr(settings)


def test_an_unknown_secret_backend_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        make(monkeypatch, CC_SECRET_BACKEND="vault")  # noqa: S106
