"""CC_ALLOWED_HOSTS names the tailnet hosts the phone may use; nothing else widens Host."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from command_center.config import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CC_ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))


def make() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_no_remote_host_by_default() -> None:
    assert make().allowed_hosts == ()


def test_reads_one_host_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_ALLOWED_HOSTS", "mac.tail1234.ts.net")
    assert make().allowed_hosts == ("mac.tail1234.ts.net",)


def test_reads_a_comma_separated_list_lowercased_and_trimmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CC_ALLOWED_HOSTS", " Mac.Tail1234.ts.net , other.ts.net,")
    assert make().allowed_hosts == ("mac.tail1234.ts.net", "other.ts.net")


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "*.ts.net",
        "https://mac.ts.net",
        "mac.ts.net:443",
        "mac.ts.net/path",
        "user@mac.ts.net",
        "mac .ts.net",
        "localhost",
        "127.0.0.1",
        "0.0.0.0",  # noqa: S104 - the value under test, never bound
    ],
)
def test_rejects_hosts_that_would_widen_the_check(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("CC_ALLOWED_HOSTS", value)
    with pytest.raises(ValidationError):
        make()


def test_error_names_the_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CC_ALLOWED_HOSTS", "*")
    with pytest.raises(ValidationError, match="allowed_hosts"):
        make()
