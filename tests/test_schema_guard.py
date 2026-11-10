"""Nothing under src creates the ledger tables except the two migrations that backfill (0232, 0247).

`item_completions` is filled once from the old `done_at` and `done_by` columns, and only in the
transaction that creates it (`ensure_completions_table`). `LedgerBase.metadata` holds both ledger
tables, so any other way to create them on a database that has `item_ledger` would leave the
completions table empty and the copy would never run.

The guard reads every file under src and flags every *reference* to a way of creating a table, not
only a call, so aliasing, `getattr`, `functools.partial` and `run_sync(...)` do not get past it.
The only `create_all` it accepts is a direct call that either names its tables as a literal list
of `<x>.tables["name"]`, or is a bare call on a declarative base that the same file defines itself
(its metadata cannot hold the ledger tables). The completions table may be named in one file only.
Known limit: a name built at run time that no constant reaches (`getattr(md, name)`) is not seen.
"""

import ast
import re
from pathlib import Path
from typing import TypeGuard

import pytest
from sqlalchemy import Engine, bindparam, create_engine, text

from builders import NOW
from command_center.core.windows import TimeWindow
from command_center.storage.sqlite_items import create_item_ledger
from command_center.storage.sqlite_ledger import LedgerBase
from command_center.storage.sqlite_types import UtcDateTime

SOURCE = Path(__file__).resolve().parent.parent / "src" / "command_center"
FORBIDDEN_NAMES = frozenset(
    {
        "create_all",
        "create",
        "CreateTable",
        "DDL",
        "sorted_tables",
        "to_metadata",
        "tometadata",
        "methodcaller",
    }
)
_CREATE_TABLE_TEXT = re.compile(r"create\s+table", re.IGNORECASE)
COMPLETIONS_TABLE = "item_completions"
COMPLETIONS_HOME = "storage/sqlite_completions.py"


def schema_bypass_lines(source: str, relative_path: str = "") -> list[int]:
    """Lines that could create a ledger table without the backfill, in one file's source."""
    tree = ast.parse(source)
    own_bases = _own_bases(tree)
    accepted: set[int] = set()
    for node in ast.walk(tree):
        if _is_create_all_call(node) and _accepted(node, own_bases, relative_path):
            accepted.add(id(node.func))
    named = _tables_looked_up_by_name(tree)
    found: set[int] = set()
    for node in ast.walk(tree):
        if _is_a_way_to_create(node, accepted, named):
            found.add(int(getattr(node, "lineno", 0)))  # every node this flags has a line
    return sorted(found)


def _is_create_all_call(node: ast.AST) -> TypeGuard[ast.Call]:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_all"
    )


def _own_bases(tree: ast.AST) -> set[str]:
    """Declarative bases this file defines: each has a fresh metadata, so no ledger table."""
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and node.name != "LedgerBase"
        and any(isinstance(base, ast.Name) and base.id == "DeclarativeBase" for base in node.bases)
    }


def _accepted(call: ast.Call, own_bases: set[str], relative_path: str) -> bool:
    for keyword in call.keywords:
        if keyword.arg == "tables":
            return _literal_table_names(keyword.value, relative_path)
    receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
    return (
        isinstance(receiver, ast.Attribute)
        and receiver.attr == "metadata"
        and isinstance(receiver.value, ast.Name)
        and receiver.value.id in own_bases
    )


def _literal_table_names(value: ast.expr, relative_path: str) -> bool:
    """A non-empty list literal of `<x>.tables["name"]`; a variable, call or `None` is refused."""
    if not (isinstance(value, ast.List) and value.elts):
        return False
    for element in value.elts:
        if not (
            isinstance(element, ast.Subscript)
            and isinstance(element.value, ast.Attribute)
            and element.value.attr == "tables"
            and isinstance(element.slice, ast.Constant)
            and isinstance(element.slice.value, str)
        ):
            return False
        if element.slice.value == COMPLETIONS_TABLE and relative_path != COMPLETIONS_HOME:
            return False
    return True


def _tables_looked_up_by_name(tree: ast.AST) -> set[int]:
    """`<x>.tables` nodes that are indexed by a literal name: the one way to reach a Table."""
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "tables"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }


def _is_a_way_to_create(node: ast.AST, accepted: set[int], named: set[int]) -> bool:
    """Every reference to a creator, and every way to hold a Table that is not a literal lookup.

    `.create` is refused on any receiver: a Table can sit in a variable or come out of a loop over
    `metadata.tables` or `sorted_tables`, and its `.create(engine)` skips the backfill.
    """
    if isinstance(node, ast.Attribute):
        if node.attr == "tables":
            return id(node) not in named
        return node.attr in FORBIDDEN_NAMES and id(node) not in accepted
    if isinstance(node, ast.Name | ast.alias):
        names = (node.id,) if isinstance(node, ast.Name) else (node.name, node.asname)
        return any(name in FORBIDDEN_NAMES for name in names)
    if isinstance(node, ast.Constant | ast.BinOp):
        text = _folded_text(node)
        return text is not None and (
            text in FORBIDDEN_NAMES or _CREATE_TABLE_TEXT.search(text) is not None
        )
    if isinstance(node, ast.Call):
        return _is_getattr_of_a_creator(node)
    return False


def _folded_text(node: ast.expr) -> str | None:
    """The string a constant or a sum of constants spells, so `"create" + "_all"` is seen."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _folded_text(node.left), _folded_text(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _is_getattr_of_a_creator(node: ast.Call) -> bool:
    if not (isinstance(node.func, ast.Name) and node.func.id in {"getattr", "__getattribute__"}):
        return False
    name = _folded_text(node.args[1]) if len(node.args) > 1 else None
    return name in FORBIDDEN_NAMES or name == "tables"


def _offenders() -> set[str]:
    return {
        f"{relative}:{line}"
        for path in SOURCE.rglob("*.py")
        for relative in [path.relative_to(SOURCE).as_posix()]
        for line in schema_bypass_lines(path.read_text(), relative)
    }


# --- the checker on snippets: what it accepts ---------------------------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        'Base.metadata.create_all(engine, tables=[Base.metadata.tables["item_ledger"]])',
        'md.create_all(engine, tables=[md.tables["a"], md.tables["b"]], checkfirst=False)',
        "class _Base(DeclarativeBase): ...\n_Base.metadata.create_all(engine)",
        "class _Base(DeclarativeBase): ...\n_Base.metadata.create_all(engine, checkfirst=False)",
        "Row.__table__.columns\nRow.__table__.c.reopened_at.type",
        'table = md.tables["item_ledger"]\nconnection.exec_driver_sql("BEGIN")',
        'connection.execute(text("ALTER TABLE item_ledger ADD COLUMN reopened_at TEXT"))',
        '"""create_all is a word in a docstring"""',
    ],
)
def test_the_checker_accepts_what_production_does(snippet: str) -> None:
    assert schema_bypass_lines(snippet) == []


def test_the_completions_table_may_be_named_in_its_own_module_only() -> None:
    call = 'md.create_all(c, tables=[md.tables["item_completions"]], checkfirst=False)'

    assert schema_bypass_lines(call, COMPLETIONS_HOME) == []
    assert schema_bypass_lines(call, "storage/sqlite_other.py") == [1]
    assert schema_bypass_lines(call) == [1]


# --- ... and what it refuses: every bypass the review found, and the plain ones -----------------


@pytest.mark.parametrize(
    ("snippet", "lines"),
    [
        ("LedgerBase.metadata.create_all(engine)", [1]),
        ("CompletionRow.metadata.create_all(engine, checkfirst=False)", [1]),
        ("LedgerBase.metadata.create_all(engine, tables=None)", [1]),
        ("LedgerBase.metadata.create_all(engine, tables=[])", [1]),
        ("LedgerBase.metadata.create_all(engine, **options)", [1]),
        ("LedgerBase.metadata.create_all(engine, [LedgerRow.__table__])", [1]),
        ("md = LedgerBase.metadata\nmd.create_all(engine)", [2]),
        # the review's bypasses
        ("from sqlalchemy import MetaData as M\nM.create_all(md, engine)", [2]),
        ("f = LedgerBase.metadata.create_all\nf(engine)", [1]),
        ("from x import create_all as make\nmake(engine)", [1]),
        ("from x import create_all\ncreate_all(engine)", [1, 2]),
        ('getattr(LedgerBase.metadata, "create_all")(engine)', [1]),
        ('getattr(LedgerBase.metadata, "create" + "_all")(engine)', [1]),
        ('LedgerBase.metadata.__getattribute__("create_all")(engine)', [1]),
        ("functools.partial(LedgerBase.metadata.create_all, engine)()", [1]),
        ("await connection.run_sync(LedgerBase.metadata.create_all)", [1]),
        ("conn.run_sync(lambda c: LedgerBase.metadata.create_all(c))", [1]),
        ("LedgerBase.metadata.create_all(engine, tables=chosen)", [1]),
        ("LedgerBase.metadata.create_all(engine, tables=make_tables())", [1]),
        ("LedgerBase.metadata.create_all(engine, tables=[t for t in all_tables])", [1]),
        ("LedgerBase.metadata.create_all(engine, tables=[the_completions_table])", [1]),
        ('LedgerBase.metadata.create_all(engine, tables=[*LedgerBase.metadata.tables["a"]])', [1]),
        ("LedgerBase.metadata.create_all(engine, tables=[LedgerBase.metadata.tables[name]])", [1]),
        # one table with no backfill
        ("CompletionRow.__table__.create(engine)", [1]),
        ('LedgerBase.metadata.tables["item_completions"].create(engine)', [1]),
        ("run(CompletionRow.__table__.create, engine)", [1]),
        ('getattr(CompletionRow.__table__, "create")(engine)', [1]),
        ("from sqlalchemy.schema import CreateTable\nconnection.execute(CreateTable(t))", [1, 2]),
        ("import sqlalchemy.schema as s\nconnection.execute(s.CreateTable(t))", [2]),
        # a Table held in a variable, or reached by iterating, is no safer than X.__table__
        ("for t in LedgerBase.metadata.sorted_tables:\n    t.create(conn)", [1, 2]),
        ("for t in md.tables.values():\n    t.create(conn)", [1, 2]),
        ("for name in md.tables:\n    pass", [1]),
        ("t = CompletionRow.__table__\nt.create(engine)", [2]),
        ('operator.methodcaller("create", engine)(t)', [1]),
        ('LedgerBase.metadata.tables["item_completions"].to_metadata(Base.metadata)', [1]),
        ('LedgerBase.metadata.tables["item_completions"].tometadata(Base.metadata)', [1]),
        # raw DDL
        ('connection.exec_driver_sql("CREATE TABLE item_completions (a int)")', [1]),
        ('connection.execute(text("create  table item_completions (a int)"))', [1]),
        ('connection.execute(DDL("select 1"))', [1]),
        # a base that is not defined in the file could be the ledger's
        ("from m import Base\nBase.metadata.create_all(engine)", [2]),
        ("class _Base(DeclarativeBase): ...\nother.metadata.create_all(engine)", [2]),
        ("class LedgerBase(DeclarativeBase): ...\nLedgerBase.metadata.create_all(engine)", [2]),
    ],
)
def test_the_checker_refuses_every_way_round_the_backfill(snippet: str, lines: list[int]) -> None:
    assert schema_bypass_lines(snippet) == lines


# --- the real tree ----------------------------------------------------------------------------


def test_the_guard_reads_every_file_under_src() -> None:
    files = {path.relative_to(SOURCE).as_posix() for path in SOURCE.rglob("*.py")}

    assert COMPLETIONS_HOME in files
    assert "storage/sqlite_ledger.py" in files
    assert "api/chat_routes.py" in files  # not only the modules that mention the ledger


def test_nothing_under_src_creates_a_ledger_table_except_the_two_migrations() -> None:
    assert _offenders() == set()


# --- the behaviour the guard protects ---------------------------------------------------------


def _old_database(tmp_path: Path) -> tuple[str, Engine]:
    """A database from before decision 0131: item_ledger with a completed row, no completions."""
    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(url)
    LedgerBase.metadata.create_all(engine)  # fine here: tests are outside src (0232)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE item_completions"))
        connection.execute(
            text(
                "INSERT INTO item_ledger (user_id, item_id, source, kind, title, done_at, done_by) "
                "VALUES ('local', 'a', 'canvas', 'assignment', 'Essay', :at, 'source'), "
                "('local', 'b', 'local', 'task', 'Mine', :at, 'user'), "
                "('local', 'c', 'canvas', 'assignment', 'Open', NULL, NULL)"
            ).bindparams(bindparam("at", type_=UtcDateTime)),
            {"at": NOW},
        )
    return url, engine


def test_building_the_store_on_an_old_ledger_copies_the_completions(tmp_path: Path) -> None:
    url, engine = _old_database(tmp_path)

    ledger = create_item_ledger(url)

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT item_id, completed_by FROM item_completions ORDER BY item_id")
        ).all()
    assert [tuple(row) for row in rows] == [("a", "source"), ("b", "user")]
    history = ledger.history(TimeWindow(start=NOW.replace(hour=0), end=NOW.replace(hour=23)))
    assert len(history) == 2


def test_building_the_store_twice_does_not_bring_back_an_undone_completion(tmp_path: Path) -> None:
    url, engine = _old_database(tmp_path)
    _ = create_item_ledger(url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM item_completions WHERE item_id = 'b'"))

    _ = create_item_ledger(url)

    with engine.connect() as connection:
        left = connection.execute(text("SELECT count(*) FROM item_completions")).scalar_one()
    assert left == 1
