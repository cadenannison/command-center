"""The LaunchAgent carries CC_ALLOWED_HOSTS and CC_PORT, and nothing else (decision 0060)."""

import plistlib
from pathlib import Path

import pytest

from command_center.desktop.launch_agent import (
    ENVIRONMENT_KEYS,
    build_plist,
    install,
    launch_environment,
    plist_path,
)

PROGRAM = ["/Users/fake/.venv/bin/python", "-m", "command_center.desktop.main"]
LOGS = Path("/Users/fake/logs")
HOSTS = "my-mac.tail1234.ts.net"


def test_the_two_settings_are_the_only_variables_a_plist_may_carry() -> None:
    assert ENVIRONMENT_KEYS == ("CC_ALLOWED_HOSTS", "CC_PORT")


def test_the_plist_carries_the_given_environment() -> None:
    env = {"CC_ALLOWED_HOSTS": HOSTS, "CC_PORT": "9000"}
    data = plistlib.loads(build_plist(PROGRAM, LOGS, env))
    assert data["EnvironmentVariables"] == env


def test_an_empty_environment_leaves_the_block_out() -> None:
    assert "EnvironmentVariables" not in plistlib.loads(build_plist(PROGRAM, LOGS, {}))


def test_a_key_that_is_not_one_of_the_two_is_refused_so_no_secret_can_be_copied_in() -> None:
    with pytest.raises(ValueError, match="CC_GEMINI_API_KEY"):
        build_plist(PROGRAM, LOGS, {"CC_GEMINI_API_KEY": "fake-key-0000000000"})


def test_a_refused_key_is_named_but_its_value_is_not_in_the_message() -> None:
    with pytest.raises(ValueError, match="PATH") as info:
        build_plist(PROGRAM, LOGS, {"PATH": "fake-key-0000000000"})
    assert "fake-key-0000000000" not in str(info.value)


def test_launch_environment_takes_only_the_two_variables_from_the_environment() -> None:
    environ = {
        "CC_ALLOWED_HOSTS": HOSTS,
        "CC_PORT": "9000",
        "CC_GEMINI_API_KEY": "fake-key-0000000000",
        "HOME": "/Users/fake",
        "PATH": "/usr/bin",
    }
    assert launch_environment(environ) == {"CC_ALLOWED_HOSTS": HOSTS, "CC_PORT": "9000"}


def test_launch_environment_skips_a_variable_that_is_unset_or_blank() -> None:
    assert launch_environment({"CC_PORT": "9000", "CC_ALLOWED_HOSTS": "  "}) == {"CC_PORT": "9000"}
    assert launch_environment({}) == {}


def test_launch_environment_trims_whitespace() -> None:
    assert launch_environment({"CC_ALLOWED_HOSTS": f" {HOSTS} "}) == {"CC_ALLOWED_HOSTS": HOSTS}


def test_the_plist_is_the_same_every_time_with_an_environment() -> None:
    env = {"CC_PORT": "9000", "CC_ALLOWED_HOSTS": HOSTS}
    assert build_plist(PROGRAM, LOGS, env) == build_plist(
        PROGRAM, LOGS, dict(reversed(env.items()))
    )


def test_install_writes_the_environment_into_the_file(tmp_path: Path) -> None:
    env = {"CC_ALLOWED_HOSTS": HOSTS, "CC_PORT": "9000"}
    install(tmp_path, PROGRAM, tmp_path / "logs", env)
    written = plistlib.loads(plist_path(tmp_path).read_bytes())
    assert written["EnvironmentVariables"] == env


def test_install_without_an_environment_still_works(tmp_path: Path) -> None:
    install(tmp_path, PROGRAM, tmp_path / "logs")
    assert "EnvironmentVariables" not in plistlib.loads(plist_path(tmp_path).read_bytes())
