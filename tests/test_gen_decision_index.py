"""scripts/gen_decision_index.py turns docs/decisions/*.md into decision-index.md (decision 0082).

The cases run on a fixture directory, so a new real decision never changes what they expect.
"""

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
    loader = SourceFileLoader("gen_decision_index_under_test", str(SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    yield module
    del sys.modules[loader.name]


def record(directory: Path, filename: str, title: str, status: str) -> None:
    number = filename[:4]
    (directory / filename).write_text(
        f"# {number}. {title}\n\nStatus: {status}\n\nContext: x\n", encoding="utf-8"
    )


def rows(index: str) -> list[list[str]]:
    table = [line for line in index.splitlines() if line.startswith("| 0")]
    return [[cell.strip() for cell in line.strip("|").split(" | ")] for line in table]


def test_every_record_is_a_row_in_number_order_with_a_link_to_its_file(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0002-second.md", "The second", "accepted")
    record(tmp_path, "0001-first.md", "The first", "accepted")

    index = gen.build_index(tmp_path)

    assert rows(index) == [
        ["0001", "[The first](../decisions/0001-first.md)", "accepted", ""],
        ["0002", "[The second](../decisions/0002-second.md)", "accepted", ""],
    ]


def test_files_without_a_number_are_not_records(gen: ModuleType, tmp_path: Path) -> None:
    record(tmp_path, "0001-first.md", "The first", "accepted")
    (tmp_path / "tooling-versions.md").write_text("# Versions\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a record", encoding="utf-8")

    assert [r[0] for r in rows(gen.build_index(tmp_path))] == ["0001"]


def test_a_record_that_says_it_is_superseded_names_its_replacement(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001-old.md", "Old", "superseded by 0002")
    record(tmp_path, "0002-new.md", "New", "accepted")

    old, new = rows(gen.build_index(tmp_path))

    assert (old[2], old[3]) == ("superseded", "0002")
    assert new[3] == ""


def test_a_record_that_says_it_supersedes_another_marks_the_other_as_replaced(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001-old.md", "Old", "superseded")
    record(tmp_path, "0002-new.md", "New", "accepted (supersedes 0001)")

    old, _new = rows(gen.build_index(tmp_path))

    assert old[3] == "0002"


def test_a_record_that_says_it_was_replaced_in_part_stays_accepted_and_says_so(
    gen: ModuleType, tmp_path: Path
) -> None:
    # Only the replaced record speaks: the replacement's own line names nothing.
    record(tmp_path, "0001-old.md", "Old", "accepted; item 3 is superseded by 0002")
    record(tmp_path, "0002-new.md", "New", "accepted")

    old, new = rows(gen.build_index(tmp_path))

    assert (old[2], old[3]) == ("accepted", "0002 (in part)")
    assert (new[2], new[3]) == ("accepted", "")


def test_a_record_that_supersedes_only_part_of_another_marks_it_in_part(
    gen: ModuleType, tmp_path: Path
) -> None:
    # Only the replacement speaks: the replaced record's own line says nothing.
    record(tmp_path, "0001-old.md", "Old", "accepted")
    record(tmp_path, "0002-new.md", "New", "accepted. Supersedes item 3 of 0001.")

    old, new = rows(gen.build_index(tmp_path))

    assert (old[2], old[3]) == ("accepted", "0002 (in part)")
    assert (new[2], new[3]) == ("accepted", "")


def test_a_record_that_says_superseded_in_part_is_in_part_even_when_marked_superseded(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001-old.md", "Old", "superseded in part by 0002")
    record(tmp_path, "0002-new.md", "New", "accepted")

    assert rows(gen.build_index(tmp_path))[0][2:] == ["superseded", "0002 (in part)"]


def test_a_partly_superseded_record_is_in_part(gen: ModuleType, tmp_path: Path) -> None:
    record(tmp_path, "0001-old.md", "Old", "superseded; partly superseded by 0002")
    record(tmp_path, "0002-new.md", "New", "accepted")

    assert rows(gen.build_index(tmp_path))[0][3] == "0002 (in part)"


def test_a_supersedes_clause_that_says_in_part_marks_a_superseded_record_in_part(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001-old.md", "Old", "superseded")
    record(tmp_path, "0002-new.md", "New", "accepted. Supersedes 0001 in part.")

    assert rows(gen.build_index(tmp_path))[0][3] == "0002 (in part)"


def test_a_record_both_sides_call_in_part_is_listed_once_as_in_part(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001-old.md", "Old", "accepted; item 3 is superseded by 0002")
    record(tmp_path, "0002-new.md", "New", "accepted. Supersedes item 3 of 0001.")

    assert rows(gen.build_index(tmp_path))[0][3] == "0002 (in part)"


def test_a_replacement_named_in_both_records_is_listed_once(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001-old.md", "Old", "superseded by 0002")
    record(tmp_path, "0002-new.md", "New", "accepted; supersedes 0001")

    old, new = rows(gen.build_index(tmp_path))

    assert (old[2], old[3]) == ("superseded", "0002")
    assert new[3] == ""


@pytest.mark.parametrize(
    "listing",
    ["0002 and 0003", "0002, 0003", "0002, 0003 and 0004", "0002, and 0003, 0004", "0002 & 0003"],
)
def test_a_list_of_replacements_in_superseded_by_names_every_number(
    gen: ModuleType, tmp_path: Path, listing: str
) -> None:
    record(tmp_path, "0001-old.md", "Old", f"superseded by {listing}")
    for number in ("0002", "0003", "0004"):
        record(tmp_path, f"{number}-x.md", number, "accepted")
    wanted = sorted(n for n in ("0002", "0003", "0004") if n in listing)

    assert rows(gen.build_index(tmp_path))[0][3] == ", ".join(wanted)


@pytest.mark.parametrize("word", ["by", "by decision", "by decisions"])
def test_superseded_by_may_say_decision(gen: ModuleType, tmp_path: Path, word: str) -> None:
    record(tmp_path, "0001-old.md", "Old", f"superseded {word} 0002")
    record(tmp_path, "0002-new.md", "New", "accepted")

    assert rows(gen.build_index(tmp_path))[0][3] == "0002"


@pytest.mark.parametrize(
    "clause", ["0002 and 0003", "0002, 0003", "0002, 0003 and 0004", "decisions 0002, 0003, 0004"]
)
def test_a_supersedes_list_marks_every_number_it_names(
    gen: ModuleType, tmp_path: Path, clause: str
) -> None:
    for number in ("0001", "0002", "0003", "0004"):
        record(tmp_path, f"{number}-x.md", number, "superseded")
    record(tmp_path, "0005-new.md", "New", f"accepted; supersedes {clause}")
    wanted = {n for n in ("0002", "0003", "0004") if n in clause}

    cells = {row[0]: row[3] for row in rows(gen.build_index(tmp_path))}

    assert {n for n, cell in cells.items() if cell == "0005"} == wanted
    assert cells["0001"] == ""


def test_every_supersedes_clause_of_a_status_line_counts(gen: ModuleType, tmp_path: Path) -> None:
    for number in ("0001", "0002", "0003"):
        record(tmp_path, f"{number}-x.md", number, "accepted")
    record(
        tmp_path,
        "0004-new.md",
        "New",
        "accepted. Supersedes item 2 of 0001. Supersedes the `f(x)` rule of 0002; supersedes 0003.",
    )

    first, second, third, _new = rows(gen.build_index(tmp_path))

    assert (first[3], second[3], third[3]) == ("0004 (in part)",) * 3


def test_a_supersedes_in_brackets_stops_at_the_closing_bracket(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001-a.md", "A", "superseded")
    record(tmp_path, "0002-b.md", "B", "accepted")
    record(tmp_path, "0003-c.md", "C", "accepted (supersedes 0001) and extends 0002")

    first, second, _third = rows(gen.build_index(tmp_path))

    assert (first[3], second[3]) == ("0003", "")


def test_numbers_after_the_supersedes_sentence_are_not_counted(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001-a.md", "A", "accepted")
    record(tmp_path, "0002-b.md", "B", "accepted")
    record(
        tmp_path,
        "0003-c.md",
        "C",
        "accepted. Supersedes the `x.y()` clause of 0001. Extended by 0002.",
    )

    first, second, _third = rows(gen.build_index(tmp_path))

    assert (first[3], second[3]) == ("0003 (in part)", "")


def test_a_pipe_in_a_title_does_not_break_the_table(gen: ModuleType, tmp_path: Path) -> None:
    record(tmp_path, "0001-a.md", "A | B", "accepted")

    assert "[A \\| B](" in gen.build_index(tmp_path)


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("No heading\n\nStatus: accepted\n", "first line must be '# 0001."),
        ("# 0009. Wrong number\n\nStatus: accepted\n", "first line must be '# 0001."),
        ("# 0001. No status\n\nContext: x\n", "no 'Status:' line"),
    ],
)
def test_a_malformed_record_fails_naming_the_file(
    gen: ModuleType, tmp_path: Path, content: str, problem: str
) -> None:
    (tmp_path / "0001-bad.md").write_text(content, encoding="utf-8")

    with pytest.raises(gen.DecisionFormatError, match=f"0001-bad.md: .*{problem}"):
        gen.build_index(tmp_path)


def test_two_records_with_one_number_fail_naming_both_files(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001-a.md", "A", "accepted")
    record(tmp_path, "0001-b.md", "B", "accepted")

    with pytest.raises(gen.DecisionFormatError, match=r"0001-b\.md: .*0001-a\.md"):
        gen.build_index(tmp_path)


def test_every_real_decision_record_follows_the_format_and_gets_its_own_row(
    gen: ModuleType,
) -> None:
    on_disk = sorted(p for p in gen.DECISIONS_DIR.glob("*.md") if p.name[:4].isdigit())

    table = rows(gen.build_index(gen.DECISIONS_DIR))  # gen:check owns freshness

    assert [row[0] for row in table] == [p.name[:4] for p in on_disk]
    assert [row[1].split("(../decisions/")[1].rstrip(")") for row in table] == [
        p.name for p in on_disk
    ]


def test_check_mode_fails_on_a_stale_index_and_passes_on_a_fresh_one(
    gen: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    record(decisions, "0001-a.md", "A", "accepted")
    index = tmp_path / "generated" / "decision-index.md"
    monkeypatch.setattr(gen, "DECISIONS_DIR", decisions)
    monkeypatch.setattr(gen, "INDEX_PATH", index)

    assert gen.main(["--check"]) == 1  # missing
    assert "stale or missing" in capsys.readouterr().err

    assert gen.main([]) == 0
    assert gen.main(["--check"]) == 0

    record(decisions, "0002-b.md", "B", "accepted")
    assert gen.main(["--check"]) == 1  # a record was added and the index not rebuilt


def test_a_malformed_record_makes_the_script_exit_non_zero_with_the_file_name(
    gen: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "0001-bad.md").write_text("nothing\n", encoding="utf-8")
    monkeypatch.setattr(gen, "DECISIONS_DIR", tmp_path)
    monkeypatch.setattr(gen, "INDEX_PATH", tmp_path / "out.md")

    assert gen.main([]) == 1
    assert "0001-bad.md" in capsys.readouterr().err
