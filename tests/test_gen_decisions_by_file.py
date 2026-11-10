"""scripts/gen_decision_index.py also builds decisions-by-file.md: path -> the decisions naming it.

The cases run on a fixture directory, so a new real decision never changes what they expect.
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


@pytest.fixture(scope="module")
def gen() -> Iterator[ModuleType]:
    loader = SourceFileLoader("gen_decision_index_by_file_under_test", str(SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    yield module
    del sys.modules[loader.name]


def record(directory: Path, number: str, where: str | None, status: str = "accepted") -> None:
    lines = [f"# {number}. Title {number}", "", f"Status: {status}", "", "Context: x"]
    if where is not None:
        lines += ["", f"Where: {where}"]
    (directory / f"{number}-record.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def entries(text: str) -> dict[str, list[str]]:
    """{path: [numbers]} from the '- path: 0001 0002' lines."""
    found: dict[str, list[str]] = {}
    for line in text.splitlines():
        if line.startswith("- "):
            path, _, numbers = line[2:].partition(": ")
            found[path] = numbers.split()
    return found


def test_a_path_lists_every_record_that_names_it_in_number_order(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0002", "`src/command_center/core/redact.py`; `docs/contracts/core.md`.")
    record(tmp_path, "0001", "`src/command_center/core/redact.py`.")

    text = gen.build_by_file(tmp_path)

    assert entries(text) == {
        "docs/contracts/core.md": ["0002"],
        "src/command_center/core/redact.py": ["0001", "0002"],
    }


def test_paths_are_sorted_so_the_file_is_stable(gen: ModuleType, tmp_path: Path) -> None:
    record(tmp_path, "0001", "`src/b.py`; `src/a.py`.")

    assert list(entries(gen.build_by_file(tmp_path))) == ["src/a.py", "src/b.py"]


def touch(root: Path, *paths: str) -> None:
    for path in paths:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("", encoding="utf-8")


def test_a_bare_file_name_means_the_one_repo_file_with_that_name(
    gen: ModuleType, tmp_path: Path
) -> None:
    decisions, repo = tmp_path / "decisions", tmp_path / "repo"
    decisions.mkdir()
    touch(repo, "src/pkg/services/agenda.py", "src/pkg/services/sync.py", "docs/MAP.md")
    record(decisions, "0001", "`src/pkg/services/sync.py`, `agenda.py`; `docs/MAP.md`.")

    assert set(entries(gen.build_by_file(decisions, repo))) == {
        "src/pkg/services/sync.py",
        "src/pkg/services/agenda.py",
        "docs/MAP.md",
    }


def test_an_ambiguous_bare_name_takes_the_folder_named_next_to_it(
    gen: ModuleType, tmp_path: Path
) -> None:
    decisions, repo = tmp_path / "decisions", tmp_path / "repo"
    decisions.mkdir()
    touch(repo, "src/pkg/services/sync.py", "src/pkg/api/sync.py")
    record(decisions, "0001", "`src/pkg/api/errors.py`, `sync.py`.")

    assert set(entries(gen.build_by_file(decisions, repo))) == {
        "src/pkg/api/errors.py",
        "src/pkg/api/sync.py",
    }


def test_a_bare_name_that_stays_ambiguous_or_is_missing_is_dropped(
    gen: ModuleType, tmp_path: Path
) -> None:
    decisions, repo = tmp_path / "decisions", tmp_path / "repo"
    decisions.mkdir()
    touch(repo, "src/pkg/services/sync.py", "src/pkg/api/sync.py")
    record(decisions, "0001", "`sync.py`, `gone.py`; `src/x.py`.")

    assert set(entries(gen.build_by_file(decisions, repo))) == {"src/x.py"}


def test_without_a_repo_root_bare_names_are_dropped(gen: ModuleType, tmp_path: Path) -> None:
    record(tmp_path, "0001", "`src/x.py`, `agenda.py`.")

    assert set(entries(gen.build_by_file(tmp_path))) == {"src/x.py"}


def test_symbols_and_patterns_are_not_paths(gen: ModuleType, tmp_path: Path) -> None:
    record(
        tmp_path,
        "0001",
        "`EventStore` in `src/x/ports.py`; `tests/test_*.py`; `src/x.py::Thing`; `a b.py`;"
        " `docs/decisions/0072-...md`.",
    )

    assert set(entries(gen.build_by_file(tmp_path))) == {"src/x/ports.py", "src/x.py"}


def test_a_root_file_with_an_extension_is_a_path(gen: ModuleType, tmp_path: Path) -> None:
    record(tmp_path, "0001", "`.gitleaks.toml`; the rule is in AGENTS.md.")

    assert set(entries(gen.build_by_file(tmp_path))) == {".gitleaks.toml"}


def test_a_fully_superseded_record_is_left_out_and_a_partly_superseded_one_stays(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001", "`src/x.py`.", status="superseded by 0003")
    record(tmp_path, "0002", "`src/x.py`.", status="accepted; superseded in part by 0003")
    record(tmp_path, "0003", "`src/x.py`.", status="accepted")

    assert entries(gen.build_by_file(tmp_path)) == {"src/x.py": ["0002", "0003"]}


def test_a_record_without_a_where_line_adds_nothing(gen: ModuleType, tmp_path: Path) -> None:
    record(tmp_path, "0001", None)
    record(tmp_path, "0002", "`src/x.py`.")

    assert entries(gen.build_by_file(tmp_path)) == {"src/x.py": ["0002"]}


def test_files_without_a_number_are_not_records(gen: ModuleType, tmp_path: Path) -> None:
    record(tmp_path, "0001", "`src/x.py`.")
    (tmp_path / "tooling-versions.md").write_text("Where: `src/y.py`\n", encoding="utf-8")

    assert set(entries(gen.build_by_file(tmp_path))) == {"src/x.py"}


def test_the_header_says_how_to_look_a_number_up(gen: ModuleType, tmp_path: Path) -> None:
    record(tmp_path, "0001", "`src/x.py`.")

    text = gen.build_by_file(tmp_path)

    assert text.startswith("# Decisions by file\n")
    assert "decision-index.md" in text
    assert "Do not edit" in text


def test_a_git_ignored_file_does_not_make_a_bare_name_ambiguous(
    gen: ModuleType, tmp_path: Path
) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("needs git")
    decisions, repo = tmp_path / "decisions", tmp_path / "repo"
    decisions.mkdir()
    touch(repo, "src/pkg/services/sync.py", "src/pkg/cache/sync.py")
    (repo / ".gitignore").write_text("src/pkg/cache/\n", encoding="utf-8")
    subprocess.run([git, "init", "-q"], cwd=repo, check=True, timeout=60)  # noqa: S603
    record(decisions, "0001", "`sync.py`.")

    assert set(entries(gen.build_by_file(decisions, repo))) == {"src/pkg/services/sync.py"}
