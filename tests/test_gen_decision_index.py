"""scripts/gen-decision-index turns docs/decisions/*.md into decision-index.md (decision 0082).

The cases run on a fixture directory, so a new real decision never changes what they expect.
"""

import sys
from collections.abc import Iterator
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "gen-decision-index"


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


def test_a_record_replaced_only_in_part_stays_accepted_and_says_so(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001-old.md", "Old", "accepted; item 3 is superseded by 0002")
    record(tmp_path, "0002-new.md", "New", "accepted. Supersedes item 3 of 0001.")

    old, _new = rows(gen.build_index(tmp_path))

    assert (old[2], old[3]) == ("accepted", "0002 (in part)")


def test_a_replacement_named_in_both_records_is_listed_once(
    gen: ModuleType, tmp_path: Path
) -> None:
    record(tmp_path, "0001-old.md", "Old", "superseded by 0002")
    record(tmp_path, "0002-new.md", "New", "accepted; supersedes 0001")

    assert rows(gen.build_index(tmp_path))[0][3] == "0002"


def test_several_replacements_are_all_listed(gen: ModuleType, tmp_path: Path) -> None:
    record(tmp_path, "0001-old.md", "Old", "superseded by 0002 and 0003")
    record(tmp_path, "0002-a.md", "A", "accepted")
    record(tmp_path, "0003-b.md", "B", "accepted")

    assert rows(gen.build_index(tmp_path))[0][3] == "0002, 0003"


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


def test_every_real_decision_record_follows_the_format_and_gets_a_row(gen: ModuleType) -> None:
    on_disk = [p for p in gen.DECISIONS_DIR.glob("*.md") if p.name[:4].isdigit()]

    assert len(rows(gen.build_index(gen.DECISIONS_DIR))) == len(on_disk)  # gen:check owns freshness


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
