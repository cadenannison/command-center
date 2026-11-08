"""The LaunchAgent that starts the menu-bar app at login. Plist content and file handling only.

The file is written but never loaded with launchctl, so it takes effect at the next login.
"""

import os
import plistlib
import tempfile
from collections.abc import Sequence
from pathlib import Path

LABEL = "com.command-center.menubar"
_FILE_MODE = 0o644
_LOG_NAME = "menubar.log"


def plist_path(home: Path) -> Path:
    """Where the user's LaunchAgent for this app lives."""
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_plist(program: Sequence[str], log_dir: Path) -> bytes:
    """The plist bytes. No environment block, so no setting or secret can be copied into it."""
    log = str(log_dir / _LOG_NAME)
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": list(program),
            "RunAtLoad": True,
            "KeepAlive": False,
            "LimitLoadToSessionType": "Aqua",
            "StandardOutPath": log,
            "StandardErrorPath": log,
        },
        sort_keys=True,
    )


def install(home: Path, program: Sequence[str], log_dir: Path) -> None:
    """Write the plist atomically, creating its folders. launchd needs it not group-writable."""
    if not program:
        msg = "program must name a command to run"
        raise ValueError(msg)
    target = plist_path(home)
    target.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as temp:
            temp.write(build_plist(program, log_dir))
        Path(temp_name).chmod(_FILE_MODE)
        Path(temp_name).replace(target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def remove(home: Path) -> None:
    """Delete the plist; fine if there is none."""
    plist_path(home).unlink(missing_ok=True)


def is_installed(home: Path) -> bool:
    """Whether the plist is present."""
    return plist_path(home).is_file()
