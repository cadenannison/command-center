"""scripts/tests_for.py also lists tests that reach a module through other src modules (0285).

The cases run on a fixture tree, so adding a real test or module never changes what they expect.
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
    loader = SourceFileLoader("tests_for_indirect_under_test", str(SCRIPT))
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


def found(tf: ModuleType, root: Path, *targets: str) -> list[tuple[str, bool]]:
    return [(hit.path, hit.indirect) for hit in tf.find_tests(root, list(targets))]


def test_a_test_of_a_module_that_imports_the_target_is_listed_as_indirect(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/redact.py")
    write(tmp_path, "src/pkg/summary.py", "from pkg.redact import redact\n")
    write(tmp_path, "tests/test_summary.py", "from pkg.summary import build\n")
    write(tmp_path, "tests/test_redact.py", "from pkg.redact import redact\n")

    assert found(tf, tmp_path, "src/pkg/redact.py") == [
        ("tests/test_redact.py", False),
        ("tests/test_summary.py", True),
    ]


def test_a_second_hop_through_src_is_listed_and_a_third_is_not(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/b.py", "from pkg.a import x\n")
    write(tmp_path, "src/pkg/c.py", "from pkg.b import x\n")
    write(tmp_path, "src/pkg/d.py", "from pkg.c import x\n")
    write(tmp_path, "tests/test_b.py", "from pkg.b import x\n")
    write(tmp_path, "tests/test_c.py", "from pkg.c import x\n")
    write(tmp_path, "tests/test_d.py", "from pkg.d import x\n")

    assert found(tf, tmp_path, "src/pkg/a.py") == [
        ("tests/test_b.py", True),
        ("tests/test_c.py", True),
    ]


def test_a_test_that_is_direct_is_never_also_marked_indirect(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/b.py", "from pkg.a import x\n")
    write(tmp_path, "tests/test_both.py", "from pkg.a import x\nfrom pkg.b import y\n")

    assert found(tf, tmp_path, "src/pkg/a.py") == [("tests/test_both.py", False)]


def test_an_import_of_a_module_from_its_package_counts_as_a_hop(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/core/redact.py")
    write(tmp_path, "src/pkg/services/summary.py", "from pkg.core import redact\n")
    write(tmp_path, "tests/test_summary.py", "from pkg.services import summary\n")

    assert found(tf, tmp_path, "src/pkg/core/redact.py") == [("tests/test_summary.py", True)]


def test_a_package_init_is_a_hop_for_what_imports_the_package(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/core/redact.py")
    write(tmp_path, "src/pkg/core/__init__.py", "from pkg.core.redact import redact\n")
    write(tmp_path, "src/pkg/web.py", "from pkg.core import redact\n")
    write(tmp_path, "tests/test_web.py", "from pkg.web import page\n")

    assert found(tf, tmp_path, "src/pkg/core/redact.py") == [
        ("tests/test_web.py", True),
    ]


def test_a_cycle_between_src_modules_ends(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py", "from pkg.b import y\n")
    write(tmp_path, "src/pkg/b.py", "from pkg.a import x\n")
    write(tmp_path, "tests/test_b.py", "from pkg.b import y\n")

    assert found(tf, tmp_path, "src/pkg/a.py") == [("tests/test_b.py", True)]


def test_a_module_that_imports_nothing_relevant_adds_no_test(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/other.py", "import json\n")
    write(tmp_path, "tests/test_other.py", "from pkg.other import x\n")

    assert found(tf, tmp_path, "src/pkg/a.py") == []


def test_a_src_file_that_does_not_parse_is_an_error_naming_it(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/broken.py", "def (:\n")

    with pytest.raises(tf.TestsForError, match=r"broken\.py"):
        tf.find_tests(tmp_path, ["src/pkg/a.py"])


def test_tests_for_still_lists_only_the_direct_importers(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/b.py", "from pkg.a import x\n")
    write(tmp_path, "tests/test_a.py", "from pkg.a import x\n")
    write(tmp_path, "tests/test_b.py", "from pkg.b import y\n")

    assert tf.tests_for(tmp_path, ["src/pkg/a.py"]) == ["tests/test_a.py"]


def test_main_marks_each_indirect_path_and_keeps_the_list_sorted(
    tf: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/b.py", "from pkg.a import x\n")
    write(tmp_path, "tests/test_a.py", "from pkg.a import x\n")
    write(tmp_path, "tests/test_0_b.py", "from pkg.b import y\n")

    assert tf.main(tmp_path, ["src/pkg/a.py"]) == 0
    assert capsys.readouterr().out == "tests/test_0_b.py (indirect)\ntests/test_a.py\n"


def test_a_path_that_does_not_exist_is_an_error_naming_it(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py")

    with pytest.raises(tf.TestsForError, match=r"src/pkg/missing\.py.*does not exist"):
        tf.find_tests(tmp_path, ["src/pkg/missing.py"])


def test_main_exits_non_zero_with_a_message_for_a_path_that_does_not_exist(
    tf: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "tests/test_a.py", "from pkg.a import x\n")

    code = tf.main(tmp_path, ["src/pkg/a.py", "src/pkg/typo.py"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "src/pkg/typo.py" in captured.err
    assert "does not exist" in captured.err


def test_a_directory_is_not_a_file_to_look_up(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py")

    with pytest.raises(tf.TestsForError, match=r"src/pkg.*does not exist"):
        tf.find_tests(tmp_path, ["src/pkg"])


def test_an_indirect_hit_must_be_a_test_file_not_a_helper_module(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/b.py", "from pkg.a import x\n")
    write(tmp_path, "tests/fakes.py", "from pkg.b import y\n")
    write(tmp_path, "tests/test_b.py", "from pkg.b import y\n")
    write(tmp_path, "tests/helper_direct.py", "from pkg.a import x\n")

    assert found(tf, tmp_path, "src/pkg/a.py") == [
        ("tests/helper_direct.py", False),
        ("tests/test_b.py", True),
    ]
