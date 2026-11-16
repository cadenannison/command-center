"""The CI integration list names every test file that is gated on a real backend (decision 0413).

The rule: a test file is gated if it names CC_TEST_POSTGRES_URL or CC_TEST_REDIS_URL, or imports a
gating symbol (GATING_SYMBOLS) from a tests/*_support.py module; helper-only imports do not count.
The integration job in .github/workflows/ci.yml runs a hand-kept list of files; this test fails when
the two sets differ and prints the difference. The comparison is textual and can be fooled by an
unusual indirection (a name built from parts, a gating symbol re-exported under another name).
"""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND_VARS = ("CC_TEST_POSTGRES_URL", "CC_TEST_REDIS_URL")
GATING_SYMBOLS = frozenset({"DATABASES", "REDIS_URL_ENV", "POSTGRES_URL_ENV", "redis_harness"})
LIST_START_RE = re.compile(r"^(\s*)- run: >-\s*$")
TEST_FILE_RE = re.compile(r"tests/test_\w+\.py")


def names_backend_var(text: str) -> bool:
    return any(name in text for name in BACKEND_VARS)


def imports_gating_symbol(text: str) -> bool:
    for node in ast.walk(ast.parse(text)):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.endswith("_support")
            and GATING_SYMBOLS & {alias.name for alias in node.names}
        ):
            return True
        if (  # `import x_support` then `x_support.DATABASES`
            isinstance(node, ast.Attribute)
            and node.attr in GATING_SYMBOLS
            and isinstance(node.value, ast.Name)
            and node.value.id.endswith("_support")
        ):
            return True
    return False


def gated_files(tests_dir: Path) -> set[str]:
    """Names of tests/test_*.py files gated directly or through a gating support symbol."""
    found: set[str] = set()
    for path in sorted(tests_dir.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue  # this file names the variables as data, it is not gated on them
        text = path.read_text(encoding="utf-8")
        if names_backend_var(text) or imports_gating_symbol(text):
            found.add(f"tests/{path.name}")
    return found


def _integration_job(lines: list[str]) -> list[str]:
    """The lines of the `integration:` job, up to the next job header."""
    start = next((i for i, line in enumerate(lines) if line == "  integration:"), None)
    assert start is not None, "no `integration:` job in the workflow"
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"^  \S", lines[i])), len(lines)
    )
    return lines[start + 1 : end]


def listed_files(workflow_text: str) -> set[str]:
    """Test files in the `run: >-` step that runs pytest with the backend variables set."""
    lines = _integration_job(workflow_text.splitlines())
    listed: set[str] = set()
    for index, line in enumerate(lines):
        match = LIST_START_RE.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        block: list[str] = []
        for body in lines[index + 1 :]:
            if body.strip() and len(body) - len(body.lstrip()) <= indent:
                break
            block.append(body)
        step = "\n".join(block)
        if "pytest" in step:
            listed |= set(TEST_FILE_RE.findall(step))
    return listed


def difference(tests_dir: Path, workflow_text: str) -> tuple[set[str], set[str]]:
    gated = gated_files(tests_dir)
    listed = listed_files(workflow_text)
    return gated - listed, listed - gated


def test_ci_integration_list_matches_the_gated_test_files() -> None:
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    missing, extra = difference(REPO / "tests", workflow)
    report = (
        "CI integration list is out of step with the backend-gated test files.\n"
        f"gated but not on the list ({len(missing)}): {sorted(missing)}\n"
        f"on the list but not gated ({len(extra)}): {sorted(extra)}"
    )
    assert not missing, report
    assert not extra, report


def _fake_repo(tmp_path: Path, listed: list[str]) -> tuple[Path, str]:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_gated_listed.py").write_text('import os\nos.environ["CC_TEST_REDIS_URL"]\n')
    (tests_dir / "test_gated_unlisted.py").write_text("# uses CC_TEST_POSTGRES_URL\n")
    (tests_dir / "test_plain.py").write_text("def test_x():\n    pass\n")
    (tests_dir / "test_via_support.py").write_text("from fake_support import DATABASES, helper\n")
    (tests_dir / "test_helper_only.py").write_text("from fake_support import helper\n")
    (tests_dir / "test_module_form.py").write_text(
        "import fake_support\nrig = fake_support.redis_harness\n"
    )
    files = " ".join(listed)
    workflow = (
        "jobs:\n"
        "  check:\n"
        "    steps:\n"
        "      - run: >-\n"
        "          uv run pytest tests/test_gated_unlisted.py\n"
        "  integration:\n"
        "    steps:\n"
        "      - run: uv sync\n"
        "      - run: >-\n"
        f"          uv run pytest --no-cov {files}\n"
        "      - run: >-\n"
        "          echo tests/test_plain.py\n"
        "  next:\n"
        "    steps: []\n"
    )
    return tests_dir, workflow


def test_detector_reports_a_gated_file_missing_from_the_list(tmp_path: Path) -> None:
    tests_dir, workflow = _fake_repo(tmp_path, ["tests/test_gated_listed.py"])
    missing, extra = difference(tests_dir, workflow)
    assert missing == {
        "tests/test_gated_unlisted.py",
        "tests/test_via_support.py",
        "tests/test_module_form.py",
    }
    assert extra == set()


def test_detector_accepts_a_listed_file_and_flags_a_stale_entry(tmp_path: Path) -> None:
    listed = [
        "tests/test_gated_listed.py",
        "tests/test_gated_unlisted.py",
        "tests/test_via_support.py",
        "tests/test_module_form.py",
        "tests/test_plain.py",
    ]
    tests_dir, workflow = _fake_repo(tmp_path, listed)
    missing, extra = difference(tests_dir, workflow)
    assert missing == set()
    assert extra == {"tests/test_plain.py"}
