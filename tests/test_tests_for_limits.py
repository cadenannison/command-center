"""scripts/tests_for.py skips hub modules as hops and caps the indirect list (decision 0285).

A hub is a module imported by more than 25 test files; going through it reaches most of the suite.
The cases run on a fixture tree, so adding a real test or module never changes what they expect.
"""

import subprocess
import sys
from collections.abc import Iterator
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "tests_for.py"
HUB_LIMIT = 25
LINE_LIMIT = 15


@pytest.fixture(scope="module")
def tf() -> Iterator[ModuleType]:
    loader = SourceFileLoader("tests_for_limits_under_test", str(SCRIPT))
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


def importers(root: Path, module: str, count: int, *, prefix: str = "test_hub") -> None:
    """`count` files under tests/ that import `module`."""
    for number in range(count):
        write(root, f"tests/{prefix}_{number:02d}.py", f"from {module} import x\n")


def listed(tf: ModuleType, root: Path, *targets: str) -> list[str]:
    return [hit.path for hit in tf.find_tests(root, list(targets))]


def test_the_limits_are_25_test_files_and_15_lines(tf: ModuleType) -> None:
    assert tf.HUB_TEST_IMPORTS == HUB_LIMIT
    assert tf.MAX_INDIRECT_LINES == LINE_LIMIT


def test_a_module_imported_by_more_than_25_tests_is_not_a_hop(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/hub.py", "from pkg.a import x\n")
    importers(tmp_path, "pkg.hub", HUB_LIMIT + 1)

    assert listed(tf, tmp_path, "src/pkg/a.py") == []


def test_a_module_imported_by_exactly_25_tests_is_still_a_hop(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/busy.py", "from pkg.a import x\n")
    importers(tmp_path, "pkg.busy", HUB_LIMIT)

    assert len(listed(tf, tmp_path, "src/pkg/a.py")) == HUB_LIMIT


def test_a_quiet_module_beside_a_hub_is_still_a_hop(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/hub.py", "from pkg.a import x\n")
    write(tmp_path, "src/pkg/quiet.py", "from pkg.a import x\n")
    importers(tmp_path, "pkg.hub", HUB_LIMIT + 1)
    write(tmp_path, "tests/test_quiet.py", "from pkg.quiet import x\n")

    assert listed(tf, tmp_path, "src/pkg/a.py") == ["tests/test_quiet.py"]


def test_a_chain_through_a_hub_is_cut_at_the_hub(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/hub.py", "from pkg.a import x\n")
    write(tmp_path, "src/pkg/top.py", "from pkg.hub import x\n")
    importers(tmp_path, "pkg.hub", HUB_LIMIT + 1)
    write(tmp_path, "tests/test_top.py", "from pkg.top import x\n")

    assert listed(tf, tmp_path, "src/pkg/a.py") == []


def test_the_target_itself_is_never_skipped_for_being_a_hub(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/hub.py")
    write(tmp_path, "src/pkg/user.py", "from pkg.hub import x\n")
    importers(tmp_path, "pkg.hub", HUB_LIMIT + 1)
    write(tmp_path, "tests/test_user.py", "from pkg.user import x\n")

    found = listed(tf, tmp_path, "src/pkg/hub.py")

    assert len(found) == HUB_LIMIT + 2
    assert "tests/test_user.py" in found
    assert "tests/test_hub_00.py" in found


def test_only_test_files_count_toward_a_hub_not_helper_modules(
    tf: ModuleType, tmp_path: Path
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/busy.py", "from pkg.a import x\n")
    importers(tmp_path, "pkg.busy", HUB_LIMIT + 1, prefix="rig")
    write(tmp_path, "tests/test_busy.py", "from pkg.busy import x\n")

    assert listed(tf, tmp_path, "src/pkg/a.py") == ["tests/test_busy.py"]


def indirect_rig(root: Path, count: int) -> None:
    write(root, "src/pkg/a.py")
    write(root, "src/pkg/b.py", "from pkg.a import x\n")
    for number in range(count):
        write(root, f"tests/test_b_{number:02d}.py", "from pkg.b import y\n")


def test_find_tests_still_returns_every_indirect_hit(tf: ModuleType, tmp_path: Path) -> None:
    indirect_rig(tmp_path, 20)

    assert len(listed(tf, tmp_path, "src/pkg/a.py")) == 20


def test_main_prints_15_indirect_lines_then_how_many_more(
    tf: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    indirect_rig(tmp_path, 20)

    assert tf.main(tmp_path, ["src/pkg/a.py"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[:-1] == [f"tests/test_b_{n:02d}.py (indirect)" for n in range(LINE_LIMIT)]
    assert lines[-1] == "+5 more"


def test_exactly_15_indirect_lines_print_no_more_line(
    tf: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    indirect_rig(tmp_path, LINE_LIMIT)

    assert tf.main(tmp_path, ["src/pkg/a.py"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == LINE_LIMIT
    assert not any(line.startswith("+") for line in lines)


def test_one_over_the_cap_says_plus_1_more(
    tf: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    indirect_rig(tmp_path, LINE_LIMIT + 1)

    assert tf.main(tmp_path, ["src/pkg/a.py"]) == 0

    assert capsys.readouterr().out.splitlines()[-1] == "+1 more"


def test_direct_lines_are_never_capped_or_counted_in_the_more(
    tf: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    indirect_rig(tmp_path, 17)
    for number in range(20):
        write(tmp_path, f"tests/test_a_{number:02d}.py", "from pkg.a import x\n")

    assert tf.main(tmp_path, ["src/pkg/a.py"]) == 0

    lines = capsys.readouterr().out.splitlines()
    direct = [line for line in lines if "(indirect)" not in line and not line.startswith("+")]
    assert len(direct) == 20
    assert len([line for line in lines if "(indirect)" in line]) == LINE_LIMIT
    assert lines[-1] == "+2 more"


def test_the_kept_indirect_lines_stay_in_path_order_among_the_direct_ones(
    tf: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    indirect_rig(tmp_path, 16)
    write(tmp_path, "tests/test_b_05a.py", "from pkg.a import x\n")

    assert tf.main(tmp_path, ["src/pkg/a.py"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[5:7] == ["tests/test_b_05.py (indirect)", "tests/test_b_05a.py"]
    assert lines[-1] == "+1 more"


def test_a_closer_hop_is_kept_before_a_farther_one_whatever_the_path(
    tf: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/b.py", "from pkg.a import x\n")
    write(tmp_path, "src/pkg/c.py", "from pkg.b import x\n")
    for number in range(LINE_LIMIT + 1):
        write(tmp_path, f"tests/test_a_{number:02d}.py", "from pkg.c import x\n")  # two hops
    write(tmp_path, "tests/test_z_close.py", "from pkg.b import x\n")  # one hop, sorts last

    assert tf.main(tmp_path, ["src/pkg/a.py"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert "tests/test_z_close.py (indirect)" in lines
    assert "tests/test_a_14.py (indirect)" not in lines
    assert "tests/test_a_13.py (indirect)" in lines
    assert lines[-1] == "+2 more"


def test_a_test_that_imports_fewer_src_modules_is_kept_before_a_broad_one(
    tf: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/b.py", "from pkg.a import x\n")
    for name in ("m1", "m2", "m3", "m4", "m5"):
        write(tmp_path, f"src/pkg/{name}.py")
    broad = "".join(f"from pkg.{name} import x\n" for name in ("b", "m1", "m2", "m3", "m4", "m5"))
    write(tmp_path, "tests/test_a_broad.py", broad)  # sorts first, imports 6 src modules
    for number in range(LINE_LIMIT):
        write(tmp_path, f"tests/test_b_{number:02d}.py", "from pkg.b import x\n")

    assert tf.main(tmp_path, ["src/pkg/a.py"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert "tests/test_a_broad.py (indirect)" not in lines
    assert lines[-1] == "+1 more"


def test_the_kept_lines_print_in_path_order_even_when_ranked_differently(
    tf: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/b.py", "from pkg.a import x\n")
    write(tmp_path, "src/pkg/c.py", "from pkg.b import x\n")
    write(tmp_path, "tests/test_a_far.py", "from pkg.c import x\n")
    write(tmp_path, "tests/test_z_near.py", "from pkg.b import x\n")

    assert tf.main(tmp_path, ["src/pkg/a.py"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "tests/test_a_far.py (indirect)",
        "tests/test_z_near.py (indirect)",
    ]


def test_a_hit_records_how_many_hops_away_it_is(tf: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "src/pkg/b.py", "from pkg.a import x\n")
    write(tmp_path, "src/pkg/c.py", "from pkg.b import x\n")
    write(tmp_path, "tests/test_a.py", "from pkg.a import x\n")
    write(tmp_path, "tests/test_b.py", "from pkg.b import x\n")
    write(tmp_path, "tests/test_c.py", "from pkg.c import x\n")

    hops = {hit.path: hit.hops for hit in tf.find_tests(tmp_path, ["src/pkg/a.py"])}

    assert hops == {"tests/test_a.py": 0, "tests/test_b.py": 1, "tests/test_c.py": 2}


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  (our own script, run with this interpreter)
        [sys.executable, "-I", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_run_as_a_command_it_prints_the_list_and_exits_zero() -> None:
    done = run_script("src/command_center/core/redact.py")

    assert done.returncode == 0
    assert "tests/test_redact.py" in done.stdout.splitlines()
    assert len([line for line in done.stdout.splitlines() if "(indirect)" in line]) <= LINE_LIMIT


def test_run_as_a_command_a_missing_path_exits_non_zero_with_a_message() -> None:
    done = run_script("src/command_center/core/no_such_module.py")

    assert done.returncode != 0
    assert done.stdout == ""
    assert "no_such_module.py" in done.stderr
