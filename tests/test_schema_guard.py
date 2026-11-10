"""No code creates the ledger tables with a bare `create_all`, which would skip the backfill (0232).

`item_completions` is filled once from the old `done_at` and `done_by` columns, and only in the
transaction that creates it (`ensure_completions_table`). `LedgerBase.metadata` holds both ledger
tables, so a `create_all` without `tables=` on a database that has `item_ledger` would create the
completions table empty and the copy would never run.
"""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "src" / "command_center"


def bare_create_all_lines(source: str) -> list[int]:
    """Lines that could create every ledger table: a `create_all` that does not name its tables.

    Any receiver counts (a variable holding the metadata too). `tables=None` and `**kwargs` do
    not name tables. A `.create(` on a mapped table (`X.__table__.create(...)`) makes one table
    with no backfill, so it is flagged as well.
    """
    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr == "create_all" and not _names_its_tables(node):
            found.append(node.lineno)
        target = node.func.value
        if (
            node.func.attr == "create"
            and isinstance(target, ast.Attribute)
            and (target.attr == "__table__")
        ):
            found.append(node.lineno)
    return found


def _names_its_tables(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg == "tables":
            return not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
    return False


def test_the_checker_flags_a_bare_create_all_and_accepts_one_that_names_its_tables() -> None:
    assert bare_create_all_lines("LedgerBase.metadata.create_all(engine)") == [1]
    assert bare_create_all_lines("CompletionRow.metadata.create_all(engine, checkfirst=False)") == [
        1
    ]
    assert bare_create_all_lines("LedgerBase.metadata.create_all(engine, tables=[t])") == []


def test_the_checker_is_not_fooled_by_an_empty_tables_argument_or_an_alias() -> None:
    assert bare_create_all_lines("LedgerBase.metadata.create_all(engine, tables=None)") == [1]
    assert bare_create_all_lines("LedgerBase.metadata.create_all(engine, **options)") == [1]
    assert bare_create_all_lines("md = LedgerBase.metadata\nmd.create_all(engine)") == [2]
    assert bare_create_all_lines("CompletionRow.__table__.create(engine)") == [1]


def test_nothing_creates_the_ledger_tables_with_a_bare_create_all() -> None:
    ledger_modules = [
        path
        for path in SOURCE.rglob("*.py")
        if "LedgerBase" in path.read_text() or "CompletionRow" in path.read_text()
    ]
    assert ledger_modules, "the guard found no module that uses the ledger tables"

    offenders = {
        f"{path.relative_to(SOURCE)}:{line}"
        for path in ledger_modules
        for line in bare_create_all_lines(path.read_text())
    }

    assert offenders == set()
