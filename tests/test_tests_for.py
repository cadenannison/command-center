"""scripts/tests_for.py lists the test files that import a given source module.

The cases run on a fixture tree, so adding a real test never changes what they expect.
"""

import sys
from collections.abc import Iterator
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "tests_for.py"


@pytest.fixture(scope="module")
def tf() -> Iterator[ModuleType]:
    loader = SourceFileLoader("tests_for_under_test", str(SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    yield module
    del sys.modules[loader.name]


def write(root: Path, relative: str, source: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_a_from_import_of_the_module_is_listed(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/core/redact.py")
    write(tmp_path, "tests/test_redact.py", "from pkg.core.redact import redact\n")
    write(tmp_path, "tests/test_other.py", "from pkg.core.schema import Event\n")

    assert tf.tests_for(tmp_path, ["src/pkg/core/redact.py"]) == ["tests/test_redact.py"]


def test_a_plain_import_of_the_module_is_listed(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/core/redact.py")
    write(tmp_path, "tests/test_a.py", "import pkg.core.redact\n")

    assert tf.tests_for(tmp_path, ["src/pkg/core/redact.py"]) == ["tests/test_a.py"]


def test_importing_the_module_from_its_package_is_listed(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/adapters/summary_gemini.py")
    write(tmp_path, "tests/test_a.py", "from pkg.adapters import summary_gemini, weather\n")

    assert tf.tests_for(tmp_path, ["src/pkg/adapters/summary_gemini.py"]) == ["tests/test_a.py"]


def test_a_package_init_means_the_package(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/core/__init__.py")
    write(tmp_path, "tests/test_a.py", "from pkg.core import Thing\n")
    write(tmp_path, "tests/test_b.py", "from pkg import core\n")
    write(tmp_path, "tests/test_c.py", "from pkg.core.redact import redact\n")

    assert tf.tests_for(tmp_path, ["src/pkg/core/__init__.py"]) == [
        "tests/test_a.py",
        "tests/test_b.py",
    ]


def test_several_targets_give_one_sorted_list_without_repeats(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/b.py")
    write(tmp_path, "tests/test_z.py", "from pkg.a import x\nfrom pkg.b import y\n")
    write(tmp_path, "tests/test_m.py", "from pkg.b import y\n")

    assert tf.tests_for(tmp_path, ["src/pkg/a.py", "src/pkg/b.py"]) == [
        "tests/test_m.py",
        "tests/test_z.py",
    ]


def test_relative_imports_and_helper_modules_do_not_count(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "tests/test_a.py", "from . import a\nfrom fakes import FakeA\n")

    assert tf.tests_for(tmp_path, ["src/pkg/a.py"]) == []


def test_a_target_outside_src_is_an_error(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "scripts/x.py")

    with pytest.raises(tf.TestsForError, match=r"scripts/x\.py"):
        tf.tests_for(tmp_path, ["scripts/x.py"])


def test_a_test_file_that_does_not_parse_is_an_error_naming_it(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "tests/test_bad.py", "def (:\n")

    with pytest.raises(tf.TestsForError, match=r"test_bad\.py"):
        tf.tests_for(tmp_path, ["src/pkg/a.py"])


def test_main_prints_one_path_per_line_and_fails_without_arguments(
    tf: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "tests/test_a.py", "from pkg.a import x\n")

    assert tf.main(tmp_path, ["src/pkg/a.py"]) == 0
    assert capsys.readouterr().out == "tests/test_a.py\n"
    assert tf.main(tmp_path, []) == 2
    assert "usage" in capsys.readouterr().err.lower()
