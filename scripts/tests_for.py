"""List the test files that cover the given source modules (`mise run test:for -- <src path>`).

Usage: tests_for.py src/command_center/core/redact.py [more paths]

Prints one repo-relative test path per line, sorted. A test that imports the module itself is
listed bare: `import a.b`, `from a.b import x` and `from a import b` all match `a/b.py`. A test that
reaches it through other src modules, up to two hops (test -> module -> module -> target), is listed
with " (indirect)" after the path (decision 0285); only a `test_*.py` file is listed that way, since
a rig or helper module cannot be run.

Two limits keep the indirect part short. A module that more than 25 test files import is a hub
and is not followed (the target itself is never skipped). At most 15 indirect lines are printed,
then "+N more": the ones kept are the closest hop first, then the tests that import the fewest src
modules, then path order, and they print in path order. Direct lines are never capped.

Only static imports count: a module loaded by name, a rig that builds it from a string, or a third
hop is not seen. A path that does not exist is an error (exit 1). Run `mise run test` (the full
gate) before saying a task is done; this only narrows the loop while you work.
"""

import ast
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
# Hops through src modules: test -> M1 -> target is one, test -> M2 -> M1 -> target is two.
MAX_HOPS = 2
# A module imported by more than this many test files is a hub: a hop through it reaches most of the
# suite, so it is not followed (decision 0285).
HUB_TEST_IMPORTS = 25
# The most indirect lines `main` prints; the rest are counted in a final "+N more" line.
MAX_INDIRECT_LINES = 15
INDIRECT_MARK = " (indirect)"


class TestsForError(ValueError):
    """A target is missing or not under src/, or a file cannot be parsed; the message names it."""

    __test__ = False


class Hit(NamedTuple):
    """One test file, whether it reaches the target only through other src modules, and how far.

    `hops` is 0 for a direct importer, else 1 or 2. `breadth` is how many src modules the file
    imports; a small one means a focused test. Both only rank the indirect hits for the cap.
    """

    path: str
    indirect: bool
    hops: int = 0
    breadth: int = 0


def _module_name(root: Path, target: str) -> str:
    """The dotted module a path under src/ stands for (a package's __init__.py is the package)."""
    path = (root / target).resolve()
    if not path.is_file():
        msg = f"{target}: does not exist (or is not a file)"
        raise TestsForError(msg)
    return _dotted(root, path, target)


def _dotted(root: Path, path: Path, label: str) -> str:
    try:
        relative = path.relative_to((root / "src").resolve())
    except ValueError as exc:
        msg = f"{label}: not under src/, so no test imports it by module name"
        raise TestsForError(msg) from exc
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported(path: Path) -> set[str]:
    """Every absolute dotted name the file imports; `from a import b` also gives `a.b`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        msg = f"{path.name}: cannot parse ({exc.msg}, line {exc.lineno})"
        raise TestsForError(msg) from exc
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _src_imports(root: Path) -> dict[str, set[str]]:
    """{module: the names it imports} for every module under root/src."""
    src = (root / "src").resolve()
    return {
        _dotted(root, path.resolve(), path.name): _imported(path)
        for path in sorted(src.rglob("*.py"))
    }


def _hubs(src_imports: dict[str, set[str]], tests: list[tuple[str, set[str]]]) -> set[str]:
    """The src modules that more than HUB_TEST_IMPORTS `test_*.py` files import."""
    counts = dict.fromkeys(src_imports, 0)
    for path, imports in tests:
        if Path(path).name.startswith("test_"):
            for module in imports & counts.keys():
                counts[module] += 1
    return {module for module, count in counts.items() if count > HUB_TEST_IMPORTS}


def _reaching(
    src_imports: dict[str, set[str]], targets: set[str], hubs: set[str]
) -> dict[str, int]:
    """{src module: hops to a target} for modules up to MAX_HOPS away; 1 is a direct importer.

    A hub is never a hop (it neither counts nor is followed through); a target is never skipped.
    """
    reached: dict[str, int] = {}
    frontier = set(targets)
    for hop in range(1, MAX_HOPS + 1):
        frontier = {
            module
            for module, imports in src_imports.items()
            if imports & frontier
            and module not in reached
            and module not in targets
            and module not in hubs
        }
        reached.update(dict.fromkeys(frontier, hop))
    return reached


def _test_files(root: Path) -> list[tuple[str, set[str]]]:
    return [
        (path.relative_to(root).as_posix(), _imported(path))
        for path in sorted((root / "tests").rglob("*.py"))
    ]


def find_tests(root: Path, targets: list[str]) -> list[Hit]:
    """The tests under root/tests that cover any target, sorted by path, direct or indirect."""
    wanted = {_module_name(root, target) for target in targets}
    graph = _src_imports(root)
    tests = _test_files(root)
    through = _reaching(graph, wanted, _hubs(graph, tests))
    hits: list[Hit] = []
    for path, imports in tests:
        if wanted & imports:
            hits.append(Hit(path, indirect=False))
        elif through.keys() & imports and Path(path).name.startswith("test_"):
            hops = min(through[module] for module in through.keys() & imports)
            hits.append(Hit(path, indirect=True, hops=hops, breadth=len(imports & graph.keys())))
    return hits


def tests_for(root: Path, targets: list[str]) -> list[str]:
    """The sorted repo-relative paths of the tests under root/tests that import any target."""
    return [hit.path for hit in find_tests(root, targets) if not hit.indirect]


def main(root: Path, argv: list[str]) -> int:
    """Entry point; returns the process exit code."""
    if not argv:
        print("usage: tests_for.py <src path> [<src path> ...]", file=sys.stderr)
        return 2
    try:
        hits = find_tests(root, argv)
    except TestsForError as exc:
        print(f"tests_for: {exc}", file=sys.stderr)
        return 1
    shown, more = _capped(hits)
    for hit in shown:
        print(hit.path + (INDIRECT_MARK if hit.indirect else ""))
    if more:
        print(f"+{more} more")
    return 0


def _capped(hits: list[Hit]) -> tuple[list[Hit], int]:
    """Every direct hit and the best MAX_INDIRECT_LINES indirect ones, and how many were left out.

    Best is the closest hop, then the fewest src modules imported, then path. The result keeps the
    order of `hits` (path order).
    """
    ranked = sorted((h for h in hits if h.indirect), key=lambda h: (h.hops, h.breadth, h.path))
    dropped = {hit.path for hit in ranked[MAX_INDIRECT_LINES:]}
    return [hit for hit in hits if hit.path not in dropped], len(dropped)


if __name__ == "__main__":
    sys.exit(main(ROOT, sys.argv[1:]))
