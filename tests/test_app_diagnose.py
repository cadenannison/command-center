"""`command-center diagnose learningsuite`: the stored feeds, read through the real secret store."""

import io
from datetime import datetime
from pathlib import Path

import pytest
import respx

from builders import NOW
from command_center.adapters.file_secret_store import FileSecretStore
from command_center.app import USAGE, run_command
from command_center.config import Settings
from command_center.core.errors import SecretStoreError
from ical_diagnose_support import (
    FEED_1,
    FEED_2,
    PRIVATE,
    calendar,
    feed,
    resolves_to_public,
    vevent,
    vtodo,
)


class FixedClock:
    def now(self) -> datetime:
        return NOW


LONG_AGO = "DTSTART:20200301T100000Z"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    resolves_to_public(monkeypatch)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, secret_backend="file")  # type: ignore[call-arg]  # noqa: S106


def run(settings: Settings, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run_command(list(argv), settings, out, err, FixedClock())
    return code, out.getvalue(), err.getvalue()


def store_feeds(settings: Settings, *urls: str) -> None:
    FileSecretStore(settings.data_dir).set("learningsuite", "urls", "\n".join(urls))


def test_without_stored_feeds_it_says_so(settings: Settings) -> None:
    code, out, err = run(settings, "diagnose", "learningsuite")
    assert code == 0
    assert "Feeds: 0" in out
    assert out.splitlines()[-1].startswith("Conclusion: no feed URLs are stored")
    assert err == ""


@respx.mock
def test_it_reads_the_stored_feeds_and_prints_only_counts(settings: Settings) -> None:
    store_feeds(settings, FEED_1, FEED_2)
    respx.get(FEED_1).mock(feed(calendar(vevent("a", LONG_AGO), vevent("b", LONG_AGO))))
    respx.get(FEED_2).mock(feed(calendar(vtodo("c", "DUE:20200401T100000Z"))))
    code, out, _ = run(settings, "diagnose", "learningsuite")
    assert code == 0
    assert "Feeds: 2" in out
    assert "Feed 1: HTTP 2xx, content-type calendar" in out
    assert "Events: 0 inside the window, 2 before it" in out
    assert "VEVENT 0, VTODO 1" in out
    assert "Conclusion: " in out
    for secret in PRIVATE:
        assert secret not in out


@respx.mock
def test_an_empty_calendar_gets_the_plain_conclusion(settings: Settings) -> None:
    store_feeds(settings, FEED_1)
    respx.get(FEED_1).mock(feed(calendar()))
    _, out, _ = run(settings, "diagnose", "learningsuite")
    assert out.splitlines()[-1] == "Conclusion: feed contains no VEVENT or VTODO"


def test_an_unavailable_secret_store_is_a_fixed_message(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object, **_kwargs: object) -> dict[str, str]:
        msg = "detail that must not be printed"
        raise SecretStoreError(msg)

    monkeypatch.setattr(FileSecretStore, "get", broken)
    code, out, _ = run(settings, "diagnose", "learningsuite")
    assert (code, out) == (1, "secret store unavailable\n")


@pytest.mark.parametrize("argv", [("diagnose",), ("diagnose", "canvas"), ("serve",)])
def test_an_unknown_subcommand_prints_usage_and_exits_2(
    settings: Settings, argv: tuple[str, ...]
) -> None:
    assert run(settings, *argv) == (2, "", USAGE + "\n")
