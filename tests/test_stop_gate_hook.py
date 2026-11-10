"""scripts/hooks/stop-gate.sh skips the gates when the tree is what the gates last looked at.

Each case runs the real script in a throwaway git repo, with a fake `mise` first on PATH that
records every call, so no real gate runs.
"""

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "scripts" / "hooks" / "stop-gate.sh"
GIT = shutil.which("git") or "git"
BASH = shutil.which("bash") or "/bin/bash"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("git") is None or shutil.which("shasum") is None,
    reason="the hook needs jq, git and shasum",
)


IDENTITY = {
    "GIT_AUTHOR_NAME": "fake",
    "GIT_AUTHOR_EMAIL": "fake@example.com",
    "GIT_COMMITTER_NAME": "fake",
    "GIT_COMMITTER_EMAIL": "fake@example.com",
}


class Rig:
    def __init__(self, tmp_path: Path, *, with_commit: bool = True) -> None:
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        self.calls = tmp_path / "mise-calls.txt"
        self.exit_code = tmp_path / "mise-exit.txt"
        self.exit_code.write_text("0", encoding="utf-8")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "mise"
        fake.write_text(
            f'#!/bin/bash\necho "$RUFF_OUTPUT_FORMAT $*" >> "{self.calls}"\n'
            f'code="$(cat "{self.exit_code}")"\n[ "$code" = hang ] && sleep 60\n'
            f'echo "gate output"\nexit "$code"\n',
            encoding="utf-8",
        )
        fake.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "CLAUDE_PROJECT_DIR": str(self.repo),
        }
        self.git("init", "-q")
        self.write("base.txt", "base\n")
        if with_commit:
            self.git("add", "base.txt")
            tree = self.git("write-tree")
            # Plumbing: no identity or signing setup, and no porcelain commit.
            base = self.git("commit-tree", tree, "-m", "base", env={**self.env, **IDENTITY})
            self.git("update-ref", "HEAD", base)

    def git(self, *args: str, env: dict[str, str] | None = None) -> str:
        done = subprocess.run(  # noqa: S603  (git on PATH, fixed arguments, a temp repo)
            [GIT, *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        return done.stdout.strip()

    def write(self, name: str, text: str) -> None:
        (self.repo / name).write_text(text, encoding="utf-8")

    def write_bytes(self, name: str, data: bytes) -> None:
        (self.repo / name).write_bytes(data)

    def stop(self, payload: str = "{}") -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603  (our own script, run against a temp repo)
            [BASH, str(HOOK)],
            input=payload,
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
            timeout=60,
        )

    def gate_runs(self) -> int:
        return (
            len(self.calls.read_text(encoding="utf-8").splitlines()) if self.calls.exists() else 0
        )


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_a_clean_tree_runs_no_gate(rig: Rig) -> None:
    assert rig.stop().returncode == 0
    assert rig.gate_runs() == 0


def test_a_dirty_tree_runs_the_fast_gates_with_concise_ruff_output(rig: Rig) -> None:
    rig.write("new.txt", "change\n")

    assert rig.stop().returncode == 0
    assert rig.calls.read_text(encoding="utf-8").strip() == "concise run check:fast"


def test_the_same_dirty_tree_is_not_checked_twice(rig: Rig) -> None:
    rig.write("new.txt", "change\n")
    rig.stop()

    assert rig.stop().returncode == 0
    assert rig.gate_runs() == 1


def test_an_edit_to_a_tracked_file_runs_the_gates_again(rig: Rig) -> None:
    rig.write("base.txt", "edited\n")
    rig.stop()
    rig.write("base.txt", "edited again\n")

    rig.stop()

    assert rig.gate_runs() == 2


def test_an_edit_to_an_untracked_file_runs_the_gates_again(rig: Rig) -> None:
    rig.write("new.txt", "one\n")
    rig.stop()
    rig.write("new.txt", "two\n")

    rig.stop()

    assert rig.gate_runs() == 2


def test_a_failing_gate_blocks_the_stop_once_and_prints_its_output(rig: Rig) -> None:
    rig.write("new.txt", "change\n")
    rig.exit_code.write_text("1", encoding="utf-8")

    first = rig.stop()
    second = rig.stop()

    assert first.returncode == 2
    assert "gate output" in first.stderr
    assert second.returncode == 0
    assert rig.gate_runs() == 1


def test_a_fix_after_a_failure_is_checked_again(rig: Rig) -> None:
    rig.write("new.txt", "broken\n")
    rig.exit_code.write_text("1", encoding="utf-8")
    rig.stop()
    rig.write("new.txt", "fixed\n")
    rig.exit_code.write_text("0", encoding="utf-8")

    assert rig.stop().returncode == 0
    assert rig.gate_runs() == 2


def test_the_loop_guard_lets_a_second_stop_through_without_running_the_gates(rig: Rig) -> None:
    rig.write("new.txt", "change\n")

    assert rig.stop('{"stop_hook_active": true}').returncode == 0
    assert rig.gate_runs() == 0


def test_a_second_edit_to_a_tracked_binary_file_is_seen(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.write_bytes("image.bin", b"\x00\x01\x02")
    rig.git("add", "image.bin")
    tree = rig.git("write-tree")
    base = rig.git("commit-tree", tree, "-p", "HEAD", "-m", "bin", env={**rig.env, **IDENTITY})
    rig.git("update-ref", "HEAD", base)
    rig.write_bytes("image.bin", b"\x00\x01\x03")
    rig.stop()
    rig.write_bytes("image.bin", b"\x00\x01\x04")

    rig.stop()

    assert rig.gate_runs() == 2


def test_a_repo_with_no_commit_yet_still_notices_edits(tmp_path: Path) -> None:
    rig = Rig(tmp_path, with_commit=False)
    rig.git("add", "base.txt")
    rig.stop()
    rig.write("base.txt", "edited\n")

    rig.stop()

    assert rig.gate_runs() == 2


def test_an_interrupted_gate_run_is_not_remembered_as_checked(rig: Rig) -> None:
    rig.write("new.txt", "change\n")
    rig.exit_code.write_text("hang", encoding="utf-8")
    hook = subprocess.Popen(  # noqa: S603  (our own script, run against a temp repo)
        [BASH, str(HOOK)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=rig.env,
        start_new_session=True,
        text=True,
    )
    assert hook.stdin is not None
    hook.stdin.write("{}")
    hook.stdin.close()
    deadline = time.monotonic() + 30
    while rig.gate_runs() == 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    os.killpg(hook.pid, signal.SIGKILL)  # what a hook timeout does: the hook dies mid-run
    hook.wait(timeout=30)
    rig.exit_code.write_text("0", encoding="utf-8")

    second = rig.stop()

    assert second.returncode == 0
    assert rig.gate_runs() == 2
