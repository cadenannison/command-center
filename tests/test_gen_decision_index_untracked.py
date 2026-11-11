"""decisions-by-file.md resolves a bare file name from tracked files, not from scratch files (0287).

Each case builds a throwaway git repo, so what CI sees (tracked files) and what a working copy
adds (untracked files) can be told apart.
"""

import shutil
import subprocess
import sys
from collections.abc import Iterator
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "gen_decision_index.py"
GIT = shutil.which("git") or "git"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


@pytest.fixture(scope="module")
def gen() -> Iterator[ModuleType]:
    loader = SourceFileLoader("gen_decision_index_untracked_under_test", str(SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    yield module
    del sys.modules[loader.name]


def git(root: Path, *args: str) -> None:
    _ = subprocess.run(  # noqa: S603  (git on PATH, fixed arguments, a temp repo)
        [GIT, "-C", str(root), *args], check=True, capture_output=True, timeout=60
    )


def touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    decisions = tmp_path / "docs" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "0001-agenda.md").write_text(
        "# 0001. Agenda\n\nStatus: accepted\n\nWhere: `agenda.py`\n", encoding="utf-8"
    )
    return tmp_path


def by_file(gen: ModuleType, repo: Path) -> str:
    return str(gen.build_by_file(repo / "docs" / "decisions", repo))


def track(repo: Path, relative: str) -> None:
    touch(repo, relative)
    git(repo, "add", relative)


def test_a_tracked_file_resolves_a_bare_name(gen: ModuleType, repo: Path) -> None:
    track(repo, "src/command_center/agenda.py")

    assert "- src/command_center/agenda.py: 0001" in by_file(gen, repo)


def test_a_new_untracked_file_under_src_resolves_before_it_is_added(
    gen: ModuleType, repo: Path
) -> None:
    touch(repo, "src/command_center/agenda.py")

    assert "- src/command_center/agenda.py: 0001" in by_file(gen, repo)


def test_an_untracked_scratch_file_in_scripts_does_not_make_a_name_ambiguous(
    gen: ModuleType, repo: Path
) -> None:
    track(repo, "src/command_center/agenda.py")
    touch(repo, "scripts/scratch/agenda.py")

    assert "- src/command_center/agenda.py: 0001" in by_file(gen, repo)


def test_an_untracked_scratch_file_in_claude_does_not_make_a_name_ambiguous(
    gen: ModuleType, repo: Path
) -> None:
    track(repo, "src/command_center/agenda.py")
    touch(repo, ".claude/tmp/agenda.py")

    assert "- src/command_center/agenda.py: 0001" in by_file(gen, repo)


def test_a_name_that_only_an_untracked_scratch_file_has_is_not_resolved(
    gen: ModuleType, repo: Path
) -> None:
    touch(repo, "scripts/scratch/agenda.py")

    assert [line for line in by_file(gen, repo).splitlines() if line.startswith("- ")] == []


def test_the_result_is_the_same_with_and_without_untracked_scratch_files(
    gen: ModuleType, repo: Path
) -> None:
    track(repo, "src/command_center/agenda.py")
    before = by_file(gen, repo)
    touch(repo, "scripts/scratch/agenda.py")
    touch(repo, ".claude/tmp/agenda.py")
    touch(repo, ".github/agenda.py")

    assert by_file(gen, repo) == before


def test_an_ignored_file_never_counts(gen: ModuleType, repo: Path) -> None:
    (repo / ".gitignore").write_text("cache/\n", encoding="utf-8")
    track(repo, "src/command_center/agenda.py")
    touch(repo, "src/command_center/cache/agenda.py")

    assert "- src/command_center/agenda.py: 0001" in by_file(gen, repo)
