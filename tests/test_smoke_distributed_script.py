"""scripts/smoke-distributed.sh never leaks a secret or runs compose without its env file (0078).

No Docker runs here: these are checks on the script's text, plus bash's own syntax check.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "smoke-distributed.sh"
TEXT = SCRIPT.read_text()
COMMENT = re.compile(r"^\s*#")
TRAILING_COMMENT = re.compile(r"\s#\s.*$")


def code_lines() -> list[str]:
    lines = [line for line in TEXT.splitlines() if not COMMENT.match(line)]
    return [TRAILING_COMMENT.sub("", line) for line in lines]


def test_the_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)


def test_it_stops_on_the_first_error_and_unset_variable() -> None:
    assert any(line.strip() == "set -euo pipefail" for line in code_lines())


def test_it_never_turns_on_tracing() -> None:
    # `set -x` (or `set -ex`, `set -o xtrace`, `bash -x`) would print every command with its data.
    joined = "\n".join(code_lines())
    assert not re.search(r"\bset\s+-[a-zA-Z]*x", joined)
    assert "xtrace" not in joined
    assert not re.search(r"bash\s+-[a-zA-Z]*x", joined)
    assert not TEXT.splitlines()[0].rstrip().endswith("-x")


def test_it_never_echoes_a_token_or_password_variable() -> None:
    # No variable of this script is named for a secret, and nothing prints one.
    for line in code_lines():
        assert not re.search(
            r"\$\{?[A-Za-z_]*(PASSWORD|TOKEN|SECRET|CREDENTIAL)", line, re.IGNORECASE
        ), line


def test_it_never_prints_a_body_or_the_env_file() -> None:
    for line in code_lines():
        assert not re.search(
            r"(^\s*|[;&|(]\s*|\$\(\s*)(cat|head|tail|source|less)\s.*\$\{?(BODY_FILE|REQUEST_FILE|COMPOSE_ENV_FILE)",
            line,
        ), line
        assert not re.match(r"\s*\.\s+.*COMPOSE_ENV_FILE", line), line
        if re.search(r"\bcurl\b", line):
            assert not re.search(r"(^|\s)(-v|--verbose|--trace\S*)(\s|$)", line), line
        assert not re.search(r"\bjq\b[^|]*'\.'\s", line), line  # a bare `jq .` prints a whole body


def test_the_env_file_is_only_passed_to_compose_by_name() -> None:
    # Only a use of the value matters; a message that names the variable does not read it.
    uses = [
        line
        for line in code_lines()
        if re.search(r"\$\{?COMPOSE_ENV_FILE", line) or line.startswith("COMPOSE_ENV_FILE=")
    ]
    for line in uses:
        allowed = (
            line.startswith("COMPOSE_ENV_FILE=")
            or '-f "$COMPOSE_ENV_FILE"' in line
            or '--env-file "$COMPOSE_ENV_FILE"' in line
        )
        assert allowed, line


def test_every_docker_compose_call_uses_env_file() -> None:
    calls = [line for line in code_lines() if re.search(r"\bdocker\s+compose\b", line)]
    assert calls, "the script should run compose"
    for line in calls:
        assert '--env-file "$COMPOSE_ENV_FILE"' in line, line
    assert "docker-compose" not in TEXT


def test_docker_is_never_run_except_through_compose() -> None:
    for line in code_lines():
        if re.search(r"(^|[;&|({]\s*|\$\(\s*)docker\b", line):
            assert re.search(r"\bdocker\s+compose\s+--env-file\b", line), line


def test_it_restarts_exactly_the_weather_worker_and_the_normalizer() -> None:
    restarted = set(re.findall(r"restart_service\s+([a-z-]+)", "\n".join(code_lines())))
    assert restarted == {"worker-weather", "normalizer"}


def test_it_does_not_hand_credentials_to_curl_on_the_command_line() -> None:
    # The coordinates go through a file, so they never show in a process list.
    assert "--data-binary" in TEXT
    for line in code_lines():
        if re.search(r"\bcurl\b", line):
            assert not re.search(r"(^|\s)(-d|--data|--data-raw)\s", line), line


def test_bash_accepts_the_syntax() -> None:
    bash = shutil.which("bash") or "/bin/bash"
    result = subprocess.run(  # noqa: S603  (our own script)
        [bash, "-n", str(SCRIPT)], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
def test_shellcheck_is_clean() -> None:
    shellcheck = shutil.which("shellcheck") or "shellcheck"
    result = subprocess.run(  # noqa: S603
        [shellcheck, str(SCRIPT)], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stdout
