"""List the test files that import the given source modules (`mise run test:for -- <src path>`).

Usage: tests_for.py src/command_center/core/redact.py [more paths]

Prints one repo-relative test path per line, sorted. Only a direct import counts: `import a.b`,
`from a.b import x` and `from a import b` all match `a/b.py`; a test that reaches the module only
through a rig or another module is not listed. Run `mise run test` (the full gate) before saying a
task is done; this only narrows the loop while you work.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestsForError(ValueError):
    """A target is not under src/, or a test file cannot be parsed; the message names it."""

    __test__ = False


def _module_name(root: Path, target: str) -> str:
    """The dotted module a path under src/ stands for (a package's __init__.py is the package)."""
    path = (root / target).resolve()
    try:
        relative = path.relative_to((root / "src").resolve())
    except ValueError as exc:
        msg = f"{target}: not under src/, so no test imports it by module name"
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


def tests_for(root: Path, targets: list[str]) -> list[str]:
    """The sorted repo-relative paths of the tests under root/tests that import any target."""
    wanted = {_module_name(root, target) for target in targets}
    found = [
        path.relative_to(root).as_posix()
        for path in sorted((root / "tests").rglob("*.py"))
        if wanted & _imported(path)
    ]
    return sorted(found)


def main(root: Path, argv: list[str]) -> int:
    """Entry point; returns the process exit code."""
    if not argv:
        print("usage: tests_for.py <src path> [<src path> ...]", file=sys.stderr)
        return 2
    try:
        found = tests_for(root, argv)
    except TestsForError as exc:
        print(f"tests_for: {exc}", file=sys.stderr)
        return 1
    for path in found:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(ROOT, sys.argv[1:]))
