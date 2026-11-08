"""The server the menu-bar app owns: the command to run it and a small process handle."""

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

_STOP_TIMEOUT_SECONDS = 5.0
_MAX_PORT = 65535
_LOG_MODE = 0o600


class ProcessHandle(Protocol):
    """The part of subprocess.Popen the handle uses."""

    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


Spawn = Callable[[list[str], Path], ProcessHandle]


def server_command(python: str, port: int) -> list[str]:
    """Serve the app factory on loopback only."""
    if not 1 <= port <= _MAX_PORT:
        msg = f"port must be 1..{_MAX_PORT}, got {port}"
        raise ValueError(msg)
    return [
        python,
        "-m",
        "uvicorn",
        "--factory",
        "command_center.app:create_app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]


def spawn_to_log(command: list[str], log_path: Path) -> ProcessHandle:
    """Start the command with its output appended to a private log file."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, _LOG_MODE)
    with os.fdopen(descriptor, "ab") as log:
        return subprocess.Popen(  # noqa: S603 - the command is built by server_command
            command, stdout=log, stderr=log, stdin=subprocess.DEVNULL
        )


class ServerProcess:
    """Starts the server once and stops it politely. `start()` after a crash spawns a new one."""

    def __init__(self, command: list[str], log_path: Path, *, spawn: Spawn = spawn_to_log) -> None:
        self._command = command
        self._log_path = log_path
        self._spawn = spawn
        self._process: ProcessHandle | None = None

    @property
    def running(self) -> bool:
        """Whether the spawned process is still alive."""
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        """Spawn the server unless it is already running."""
        if not self.running:
            self._process = self._spawn(self._command, self._log_path)

    def stop(self) -> None:
        """Terminate, then kill a process that will not exit."""
        process, self._process = self._process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=_STOP_TIMEOUT_SECONDS)
        except (TimeoutError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=_STOP_TIMEOUT_SECONDS)
