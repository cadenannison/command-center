"""scripts/gen_module_index.py turns the module docstrings under src/ into module-index.md.

The cases run on a fixture tree, so editing a real module never changes what they expect.
"""

import sys
from collections.abc import Iterator
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "gen_module_index.py"


@pytest.fixture(scope="module")
def gen() -> Iterator[ModuleType]:
    loader = SourceFileLoader("gen_module_index_under_test", str(SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    yield module
    del sys.modules[loader.name]


def write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(("- ", "## "))]


def test_modules_are_listed_by_folder_with_the_first_docstring_line(
    gen: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "pkg/app.py", '"""The composition root."""\n')
    write(tmp_path, "pkg/core/b.py", '"""Second."""\n')
    write(tmp_path, "pkg/core/a.py", '"""First."""\n')

    text = gen.build_module_index(tmp_path / "pkg")

    assert lines(text) == [
        "## (root)",
        "- `app.py`: The composition root.",
        "## core/",
        "- `a.py`: First.",
        "- `b.py`: Second.",
    ]


def test_init_files_and_caches_are_not_listed(gen: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "pkg/__init__.py", '"""Package."""\n')
    write(tmp_path, "pkg/core/__init__.py", "")
    write(tmp_path, "pkg/core/a.py", '"""First."""\n')
    write(tmp_path, "pkg/core/__pycache__/a.cpython-313.py", '"""Cached."""\n')

    assert lines(gen.build_module_index(tmp_path / "pkg")) == ["## core/", "- `a.py`: First."]


def test_the_summary_is_the_first_sentence_of_the_first_paragraph_on_one_line(
    gen: ModuleType, tmp_path: Path
) -> None:
    write(
        tmp_path,
        "pkg/a.py",
        '"""Decide which rows\n    are current. Then more.\n\n    Second paragraph."""\n',
    )

    assert "- `a.py`: Decide which rows are current." in gen.build_module_index(tmp_path / "pkg")


def test_e_g_and_i_e_do_not_end_the_sentence(gen: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "pkg/a.py", '"""Adapters, e.g. Canvas, i.e. sources. Then more."""\n')

    assert "- `a.py`: Adapters, e.g. Canvas, i.e. sources." in gen.build_module_index(
        tmp_path / "pkg"
    )


def test_a_long_summary_is_cut_with_an_ellipsis(gen: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "pkg/a.py", '"""' + "word " * 60 + '"""\n')

    (entry,) = [x for x in lines(gen.build_module_index(tmp_path / "pkg")) if x.startswith("- ")]

    assert entry.endswith("...")
    assert len(entry) <= len("- `a.py`: ") + gen.MAX_SUMMARY


def test_a_module_without_a_docstring_says_so(gen: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "pkg/a.py", "x = 1\n")

    assert "- `a.py`: (no docstring)" in gen.build_module_index(tmp_path / "pkg")


def test_a_file_that_does_not_parse_is_an_error_naming_it(gen: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "pkg/bad.py", "def (:\n")

    with pytest.raises(gen.ModuleIndexError, match=r"bad\.py"):
        gen.build_module_index(tmp_path / "pkg")


def test_the_header_says_it_is_generated_and_where_the_rest_lives(
    gen: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "pkg/a.py", '"""First."""\n')

    text = gen.build_module_index(tmp_path / "pkg")

    assert text.startswith("# Module index\n")
    assert "Do not edit" in text
    assert "docs/MAP.md" in text
