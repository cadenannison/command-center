"""scripts/report-state.sh prints only what is safe to paste, even from a hostile response (0078).

`curl` is replaced by a stub on PATH that serves fixture files: no server, no network.
"""

import json
import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "report-state.sh"
FAKE_TOKEN = "fake-canvas-token-1234567890abcdef"  # noqa: S105  (a test value)
FAKE_URL = (
    "https://fake-school.instructure.com/api/v1/courses?access_token=fake-url-token-0987654321"
)

STUB_CURL = """#!/usr/bin/env bash
out=""; url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w|--max-time) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
[[ -z "${STUB_DOWN:-}" ]] || exit 7
case "$url" in
  */v1/settings*) cat "$FIXTURE_DIR/settings.json" >"$out" ;;
  */v1/events*)
    [[ -z "${STUB_NO_EVENTS:-}" ]] || { printf 500; exit 0; }
    cat "$FIXTURE_DIR/events.json" >"$out" ;;
esac
printf 200
"""

SETTINGS = [
    {
        "source": "canvas",
        "keys": {
            "base_url": {"set": True, "last4": "s.com"},
            # A buggy api returning the whole value as "last4": the script must still cut it to 4.
            "access_token": {"set": True, "last4": FAKE_TOKEN},
        },
        "sync": {
            "source": "canvas",
            "status": "reconnect",
            "message": (
                f"Canvas rejected {FAKE_TOKEN} for bob@example.com (code 123456789) at {FAKE_URL}"
            ),
            "at": "2026-11-08T10:00:00Z",
        },
        "value": FAKE_TOKEN,  # a field no response has; it must not be printed either
    },
    {"source": "gmail", "keys": {"client": {"set": False, "last4": None}}, "sync": None},
    {
        "source": "apple_calendar",
        "keys": {
            FAKE_TOKEN: {"set": True, "last4": "ab12"},
            "apple_id": {"set": True, "last4": ".com"},
        },
        "sync": {
            "source": "apple_calendar",
            "status": "ok",
            "message": "",
            "at": "2026-11-08T10:05:00Z",
        },
    },
    {
        "source": "weather",
        "keys": {"latitude": {"set": True, "last4": "6040"}},
        "sync": {"source": "weather", "status": FAKE_TOKEN, "message": "", "at": FAKE_TOKEN},
    },
]
EVENTS = [
    {"source": "canvas", "title": "fake-secret-title-one"},
    {"source": "canvas", "title": "fake-secret-title-two"},
    {"source": "weather", "title": "fake-secret-title-three"},
]


Report = Callable[..., subprocess.CompletedProcess[str]]


def run_bash(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash") or "/bin/bash"
    return subprocess.run(  # noqa: S603  (our own script and fixed arguments)
        [bash, *args], env=env, capture_output=True, text=True, check=False, timeout=60
    )


@pytest.fixture
def run_report(tmp_path: Path) -> Report:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(STUB_CURL)
    curl.chmod(0o755)
    (tmp_path / "settings.json").write_text(json.dumps(SETTINGS))
    (tmp_path / "events.json").write_text(json.dumps(EVENTS))

    def run(**extra: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "TMPDIR": str(tmp_path),
            "FIXTURE_DIR": str(tmp_path),
            **extra,
        }
        return run_bash(str(SCRIPT), env=env)

    return run


def test_the_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)


def test_a_fake_token_in_the_api_response_never_reaches_the_output(run_report: Report) -> None:
    result = run_report()
    shown = result.stdout + result.stderr
    assert result.returncode == 0, shown
    assert FAKE_TOKEN not in shown
    assert FAKE_TOKEN[:-4] not in shown  # not even all but the last four characters
    assert "fake-" not in shown  # no fake-looking value at all: tokens, urls and titles
    assert "bob@example.com" not in shown
    assert "123456789" not in shown
    assert "instructure" not in shown


def test_it_prints_status_message_last4_and_counts_per_source(run_report: Report) -> None:
    shown = run_report().stdout
    assert "canvas: status=reconnect  synced=2026-11-08T10:00:00Z  events=2" in shown
    assert re.search(
        r"message: Canvas rejected \[redacted\] for \[email\] \(code \[number\]\)", shown
    )
    assert "base_url=ends .com" in shown
    assert "access_token=ends cdef" in shown  # cut to four characters
    assert "gmail: status=none  events=0" in shown
    assert "client=none" in shown
    assert "apple_calendar: status=ok  synced=2026-11-08T10:05:00Z  events=0" in shown
    assert "weather: status=unknown  synced=unknown  events=1" in shown
    assert "latitude=ends 6040" in shown


def test_a_key_name_that_is_not_a_plain_name_is_not_shown(run_report: Report) -> None:
    shown = run_report().stdout
    assert "?=ends ab12" in shown
    assert "apple_id=ends .com" in shown


def test_it_prints_the_commit_and_the_app_version(run_report: Report) -> None:
    shown = run_report().stdout
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert f"app version: {version}" in shown
    assert re.search(r"git commit: [0-9a-f]{7,}", shown)


def test_it_prints_no_event_title_and_no_url(run_report: Report) -> None:
    shown = run_report().stdout
    assert "secret-title" not in shown
    assert "http" not in shown


def test_unreachable_api_is_reported_without_a_traceback_or_a_token(run_report: Report) -> None:
    result = run_report(STUB_DOWN="1")
    shown = result.stdout + result.stderr
    assert result.returncode == 1
    assert "not reachable" in shown
    assert "git commit:" in shown
    assert FAKE_TOKEN not in shown


def test_unreadable_events_show_unknown_counts_and_the_rest_still_prints(
    run_report: Report,
) -> None:
    shown = run_report(STUB_NO_EVENTS="1").stdout
    assert "events=unknown" in shown
    assert "gmail: status=none" in shown


def test_it_never_turns_on_tracing_or_reads_secret_places() -> None:
    text = SCRIPT.read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"\bset\s+-[a-zA-Z]*x", code)
    assert "xtrace" not in code
    for place in (
        "compose.env",
        ".config/command-center",
        "secrets.json",
        "keyring",
        "security find",
    ):
        assert place not in code


def test_bash_accepts_the_syntax() -> None:
    assert run_bash("-n", str(SCRIPT)).returncode == 0


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
def test_shellcheck_is_clean() -> None:
    shellcheck = shutil.which("shellcheck") or "shellcheck"
    result = subprocess.run(  # noqa: S603
        [shellcheck, str(SCRIPT)], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stdout
