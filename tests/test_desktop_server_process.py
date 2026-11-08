"""Starting and stopping the server the menu-bar app owns, with a fake process."""

from pathlib import Path

import pytest

from command_center.desktop.server_process import ServerProcess, server_command


class FakeProcess:
    def __init__(self, *, exits_on_terminate: bool = True) -> None:
        self.terminated = False
        self.killed = False
        self._exits_on_terminate = exits_on_terminate
        self._alive = True

    def poll(self) -> int | None:
        return None if self._alive else 0

    def terminate(self) -> None:
        self.terminated = True
        if self._exits_on_terminate:
            self._alive = False

    def kill(self) -> None:
        self.killed = True
        self._alive = False

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
        if self._alive:
            raise TimeoutError
        return 0


class Spawner:
    def __init__(self, process: FakeProcess) -> None:
        self.process = process
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], log_path: Path) -> FakeProcess:
        self.calls.append(command)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        return self.process


def test_the_command_serves_the_app_on_loopback_only() -> None:
    command = server_command("/venv/bin/python", 8765)
    assert command[:3] == ["/venv/bin/python", "-m", "uvicorn"]
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "8765"
    assert "--factory" in command
    assert "command_center.app:create_app" in command


def test_the_command_never_binds_beyond_loopback() -> None:
    assert "0.0.0.0" not in server_command("python", 1)  # noqa: S104 - asserting it is absent


def test_start_spawns_once(tmp_path: Path) -> None:
    spawner = Spawner(FakeProcess())
    server = ServerProcess(["serve"], tmp_path / "server.log", spawn=spawner)
    server.start()
    server.start()
    assert len(spawner.calls) == 1
    assert server.running


def test_stop_terminates_the_process(tmp_path: Path) -> None:
    process = FakeProcess()
    server = ServerProcess(["serve"], tmp_path / "server.log", spawn=Spawner(process))
    server.start()
    server.stop()
    assert process.terminated
    assert not process.killed
    assert not server.running


def test_stop_kills_a_process_that_ignores_terminate(tmp_path: Path) -> None:
    process = FakeProcess(exits_on_terminate=False)
    server = ServerProcess(["serve"], tmp_path / "server.log", spawn=Spawner(process))
    server.start()
    server.stop()
    assert process.killed


def test_stop_without_start_does_nothing(tmp_path: Path) -> None:
    ServerProcess(["serve"], tmp_path / "server.log", spawn=Spawner(FakeProcess())).stop()


def test_a_server_that_died_is_not_running(tmp_path: Path) -> None:
    process = FakeProcess()
    server = ServerProcess(["serve"], tmp_path / "server.log", spawn=Spawner(process))
    server.start()
    process.kill()
    assert not server.running


def test_start_after_a_crash_spawns_again(tmp_path: Path) -> None:
    process = FakeProcess()
    spawner = Spawner(process)
    server = ServerProcess(["serve"], tmp_path / "server.log", spawn=spawner)
    server.start()
    process.kill()
    server.start()
    assert len(spawner.calls) == 2


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_a_bad_port_is_refused(port: int) -> None:
    with pytest.raises(ValueError, match="port"):
        server_command("python", port)
