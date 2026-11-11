"""scripts/hooks/stop-gate.sh says so when it skips the gates, and keeps its stamp per worktree.

Decision 0289. These run the real script in a throwaway git repo with a fake `mise` first on PATH,
the same rig as test_stop_gate_hook.py.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from test_stop_gate_hook import BASH, GIT, HOOK, Rig

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("git") is None or shutil.which("shasum") is None,
    reason="the hook needs jq, git and shasum",
)


def run_hook(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  (our own script, run against a temp repo)
        [BASH, str(HOOK)],
        input="{}",
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )


def path_with(tmp_path: Path, name: str, *, tools: list[str]) -> str:
    """A PATH holding only the named tools (symlinks to the real ones), so the others are absent."""
    folder = tmp_path / name
    folder.mkdir()
    for tool in tools:
        real = shutil.which(tool)
        assert real is not None, tool
        (folder / tool).symlink_to(real)
    return str(folder)


def skip_lines(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in result.stderr.splitlines() if line.strip()]


def test_a_missing_jq_skips_the_gates_with_one_line_on_stderr(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.write("new.txt", "change\n")
    mise = Path(rig.env["PATH"].split(":")[0]) / "mise"
    rig.env["PATH"] = path_with(tmp_path, "only-mise", tools=[])
    (Path(rig.env["PATH"]) / "mise").symlink_to(mise)

    result = rig.stop()

    assert result.returncode == 0
    assert rig.gate_runs() == 0
    lines = skip_lines(result)
    assert len(lines) == 1
    assert "skipped" in lines[0]
    assert "jq" in lines[0]
    assert "mise" not in lines[0]


def test_a_missing_mise_skips_the_gates_with_one_line_on_stderr(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.write("new.txt", "change\n")
    rig.env["PATH"] = path_with(tmp_path, "only-jq", tools=["jq"])

    result = rig.stop()

    assert result.returncode == 0
    lines = skip_lines(result)
    assert len(lines) == 1
    assert "skipped" in lines[0]
    assert "mise" in lines[0]
    assert "jq" not in lines[0]


def test_both_missing_is_still_one_line_that_names_both(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.env["PATH"] = path_with(tmp_path, "nothing", tools=[])

    result = rig.stop()

    assert result.returncode == 0
    lines = skip_lines(result)
    assert len(lines) == 1
    assert "jq" in lines[0]
    assert "mise" in lines[0]


def test_a_skip_prints_nothing_to_stdout(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.env["PATH"] = path_with(tmp_path, "nothing", tools=[])

    assert rig.stop().stdout == ""


def test_with_both_tools_present_nothing_is_said_about_a_skip(rig_dir: Rig) -> None:
    rig_dir.write("new.txt", "change\n")

    result = rig_dir.stop()

    assert result.returncode == 0
    assert result.stderr == ""


@pytest.fixture
def rig_dir(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_an_untracked_file_with_spaces_in_its_name_is_seen_when_it_changes(rig_dir: Rig) -> None:
    rig_dir.write("my notes (draft).txt", "one\n")
    rig_dir.stop()
    rig_dir.write("my notes (draft).txt", "two\n")

    rig_dir.stop()

    assert rig_dir.gate_runs() == 2


def test_an_unchanged_untracked_file_with_spaces_is_not_checked_twice(rig_dir: Rig) -> None:
    rig_dir.write("my notes (draft).txt", "one\n")
    rig_dir.stop()

    assert rig_dir.stop().returncode == 0
    assert rig_dir.gate_runs() == 1


def worktree(rig: Rig, tmp_path: Path) -> dict[str, str]:
    """Add a linked worktree of the rig's repo and return an env that points the hook at it."""
    linked = tmp_path / "linked"
    rig.git("worktree", "add", "-q", "-b", "side", str(linked))
    return {**rig.env, "CLAUDE_PROJECT_DIR": str(linked)}


def test_a_worktree_keeps_its_own_stamp_apart_from_the_main_checkout(
    rig_dir: Rig, tmp_path: Path
) -> None:
    linked_env = worktree(rig_dir, tmp_path)
    rig_dir.write("main-only.txt", "change\n")
    (tmp_path / "linked" / "side-only.txt").write_text("change\n", encoding="utf-8")

    assert rig_dir.stop().returncode == 0
    assert run_hook(linked_env).returncode == 0

    assert rig_dir.gate_runs() == 2  # one run in each, not one shared stamp that hides the second


def test_each_worktree_is_skipped_on_its_own_unchanged_tree(rig_dir: Rig, tmp_path: Path) -> None:
    linked_env = worktree(rig_dir, tmp_path)
    rig_dir.write("main-only.txt", "change\n")
    (tmp_path / "linked" / "side-only.txt").write_text("change\n", encoding="utf-8")
    rig_dir.stop()
    run_hook(linked_env)

    rig_dir.stop()
    run_hook(linked_env)

    assert rig_dir.gate_runs() == 2


def test_an_edit_in_one_worktree_does_not_rerun_the_gates_in_the_other(
    rig_dir: Rig, tmp_path: Path
) -> None:
    linked_env = worktree(rig_dir, tmp_path)
    rig_dir.write("main-only.txt", "change\n")
    side = tmp_path / "linked" / "side-only.txt"
    side.write_text("change\n", encoding="utf-8")
    rig_dir.stop()
    run_hook(linked_env)
    side.write_text("edited\n", encoding="utf-8")

    rig_dir.stop()
    run_hook(linked_env)

    assert rig_dir.gate_runs() == 3  # only the edited worktree ran again


def test_the_stamps_live_in_two_different_git_paths(rig_dir: Rig, tmp_path: Path) -> None:
    linked_env = worktree(rig_dir, tmp_path)
    rig_dir.write("main-only.txt", "change\n")
    (tmp_path / "linked" / "side-only.txt").write_text("change\n", encoding="utf-8")
    rig_dir.stop()
    run_hook(linked_env)

    def stamp_in(folder: Path) -> Path:
        out = subprocess.run(  # noqa: S603  (git on PATH, fixed arguments, a temp repo)
            [GIT, "rev-parse", "--git-path", "cc-stop-gate.sha"],
            cwd=folder,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
        return (folder / out).resolve()

    main_stamp = stamp_in(rig_dir.repo)
    linked_stamp = stamp_in(tmp_path / "linked")

    assert main_stamp != linked_stamp
    assert main_stamp.exists()
    assert linked_stamp.exists()
