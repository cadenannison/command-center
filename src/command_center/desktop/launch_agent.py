"""The LaunchAgent that starts the menu-bar app at login. Plist content and file handling only.

The file is written but never loaded with launchctl, so it takes effect at the next login.
"""

import os
import plistlib
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

LABEL = "com.command-center.menubar"
_FILE_MODE = 0o644
_LOG_NAME = "menubar.log"

# The only variables a plist may carry: neither is secret. launchd starts the app with no CC_*
# settings, so without these the server it launches would refuse the tailnet name (decision 0060).
ENVIRONMENT_KEYS = ("CC_ALLOWED_HOSTS", "CC_PORT")


def plist_path(home: Path) -> Path:
    """Where the user's LaunchAgent for this app lives."""
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def launch_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The `ENVIRONMENT_KEYS` that are set and not blank in `environ`; nothing else is copied."""
    return {
        key: value.strip() for key in ENVIRONMENT_KEYS if (value := environ.get(key, "")).strip()
    }


def build_plist(
    program: Sequence[str], log_dir: Path, environment: Mapping[str, str] | None = None
) -> bytes:
    """The plist bytes. `environment` may hold only `ENVIRONMENT_KEYS`, so no secret fits in it."""
    unexpected = sorted(set(environment or {}) - set(ENVIRONMENT_KEYS))
    if unexpected:
        msg = f"the plist may only carry {', '.join(ENVIRONMENT_KEYS)}, not {', '.join(unexpected)}"
        raise ValueError(msg)
    log = str(log_dir / _LOG_NAME)
    content: dict[str, object] = {
        "Label": LABEL,
        "ProgramArguments": list(program),
        "RunAtLoad": True,
        "KeepAlive": False,
        "LimitLoadToSessionType": "Aqua",
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }
    if environment:
        content["EnvironmentVariables"] = dict(environment)
    return plistlib.dumps(content, sort_keys=True)


def install(
    home: Path,
    program: Sequence[str],
    log_dir: Path,
    environment: Mapping[str, str] | None = None,
) -> None:
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
            temp.write(build_plist(program, log_dir, environment))
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
