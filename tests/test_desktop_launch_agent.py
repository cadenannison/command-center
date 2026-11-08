"""The LaunchAgent that starts the menu-bar app at login: plist content and install/remove."""

import plistlib
import stat
from pathlib import Path

from command_center.desktop.launch_agent import (
    LABEL,
    build_plist,
    install,
    is_installed,
    plist_path,
    remove,
)

PROGRAM = ["/Users/fake/.venv/bin/python", "-m", "command_center.desktop.main"]


def test_the_plist_runs_the_program_at_load_under_a_stable_label() -> None:
    data = plistlib.loads(build_plist(PROGRAM, Path("/Users/fake/logs")))
    assert data["Label"] == LABEL == "com.command-center.menubar"
    assert data["ProgramArguments"] == PROGRAM
    assert data["RunAtLoad"] is True


def test_quitting_the_app_does_not_relaunch_it() -> None:
    data = plistlib.loads(build_plist(PROGRAM, Path("/Users/fake/logs")))
    assert data["KeepAlive"] is False


def test_the_app_only_runs_in_a_graphical_login_session() -> None:
    data = plistlib.loads(build_plist(PROGRAM, Path("/Users/fake/logs")))
    assert data["LimitLoadToSessionType"] == "Aqua"


def test_output_goes_to_log_files_in_the_given_directory() -> None:
    data = plistlib.loads(build_plist(PROGRAM, Path("/Users/fake/logs")))
    assert data["StandardOutPath"] == "/Users/fake/logs/menubar.log"
    assert data["StandardErrorPath"] == "/Users/fake/logs/menubar.log"


def test_the_plist_carries_no_environment_so_no_secret_can_be_in_it() -> None:
    data = plistlib.loads(build_plist(PROGRAM, Path("/Users/fake/logs")))
    assert "EnvironmentVariables" not in data


def test_the_plist_is_the_same_every_time() -> None:
    assert build_plist(PROGRAM, Path("/x")) == build_plist(PROGRAM, Path("/x"))


def test_the_plist_lives_in_the_users_launch_agents_folder(tmp_path: Path) -> None:
    assert plist_path(tmp_path) == tmp_path / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def test_install_writes_the_plist_and_creates_the_folders(tmp_path: Path) -> None:
    install(tmp_path, PROGRAM, tmp_path / "logs")
    written = plistlib.loads(plist_path(tmp_path).read_bytes())
    assert written["ProgramArguments"] == PROGRAM
    assert (tmp_path / "logs").is_dir()
    assert is_installed(tmp_path)


def test_install_is_not_writable_by_others(tmp_path: Path) -> None:
    install(tmp_path, PROGRAM, tmp_path / "logs")
    mode = stat.S_IMODE(plist_path(tmp_path).stat().st_mode)
    assert mode & (stat.S_IWGRP | stat.S_IWOTH) == 0


def test_install_twice_replaces_the_file(tmp_path: Path) -> None:
    install(tmp_path, PROGRAM, tmp_path / "logs")
    install(tmp_path, [*PROGRAM, "--again"], tmp_path / "logs")
    written = plistlib.loads(plist_path(tmp_path).read_bytes())
    assert written["ProgramArguments"][-1] == "--again"
    assert list(plist_path(tmp_path).parent.iterdir()) == [plist_path(tmp_path)]


def test_remove_deletes_the_plist(tmp_path: Path) -> None:
    install(tmp_path, PROGRAM, tmp_path / "logs")
    remove(tmp_path)
    assert not is_installed(tmp_path)


def test_remove_when_nothing_is_installed_is_fine(tmp_path: Path) -> None:
    remove(tmp_path)
    assert not is_installed(tmp_path)
