#!/usr/bin/env python3
"""Build docs/generated/decision-index.md from docs/decisions/NNNN-*.md (decision 0082).

Usage: gen_decision_index.py          write the index in place
       gen_decision_index.py --check  fail if the committed index is stale

`mise run gen:build` and `gen:check` reach this through scripts/gen_docs.py, which asks for
`build_index` and keeps the file with the other generated ones.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISIONS_DIR = ROOT / "docs" / "decisions"
INDEX_PATH = ROOT / "docs" / "generated" / "decision-index.md"
INDEX_NAME = "decision-index.md"

_FILE = re.compile(r"^(\d{4})-.+\.md$")
_TITLE = re.compile(r"^#\s+(\d{4})\.\s+(.+?)\s*$")
_STATUS = re.compile(r"^Status:\s*(.+?)\s*$", re.MULTILINE)
_KEYWORD = re.compile(r"[A-Za-z]+")
# "superseded by 0060", "superseded by decision 0060", "partly superseded by 0060, 0061 and 0062",
# "superseded in part by 0060".
_NUMBER_LIST = r"\d{4}(?:\s*(?:,\s*(?:and\s+)?|and\s+|&\s*)\d{4})*"
_SUPERSEDED_BY = re.compile(
    rf"(?P<part>partly\s+)?superseded(?P<in_part>\s+in\s+part)?\s+by\s+(?:decisions?\s+)?"
    rf"(?P<numbers>{_NUMBER_LIST})",
    re.IGNORECASE,
)
_SUPERSEDES = re.compile(r"\bsupersedes\b", re.IGNORECASE)
_IN_PART = re.compile(r"\bin\s+part\b|\bpartly\b", re.IGNORECASE)
_NUMBER = re.compile(r"\d{4}")


class DecisionFormatError(ValueError):
    """A file in docs/decisions does not follow the record format; the message names it."""


@dataclass(frozen=True)
class Decision:
    """One record: its number, title, Status line, and the numbers that line says it replaces."""

    number: str
    title: str
    status: str
    filename: str
    superseded_by: frozenset[str]
    superseded_by_in_part: frozenset[str]
    supersedes: frozenset[str]
    supersedes_in_part: frozenset[str]

    @property
    def keyword(self) -> str:
        """The first word of the Status line: accepted, superseded, proposed ..."""
        match = _KEYWORD.match(self.status)
        return match.group(0).lower() if match else ""


def parse_decision(path: Path) -> Decision:
    """Read one record; raise DecisionFormatError if the title or Status line is missing."""
    text = path.read_text(encoding="utf-8")
    file_match = _FILE.match(path.name)
    if file_match is None:
        msg = f"{path.name}: the file name must start with a four-digit number and a dash"
        raise DecisionFormatError(msg)
    title = _TITLE.match(text.splitlines()[0]) if text else None
    if title is None or title.group(1) != file_match.group(1):
        msg = f"{path.name}: the first line must be '# {file_match.group(1)}. <title>'"
        raise DecisionFormatError(msg)
    status = _STATUS.search(text)
    if status is None:
        msg = f"{path.name}: there is no 'Status:' line"
        raise DecisionFormatError(msg)
    status_text = status.group(1)
    superseded_by: set[str] = set()
    superseded_by_in_part: set[str] = set()
    for match in _SUPERSEDED_BY.finditer(status_text):
        in_part = match.group("part") is not None or match.group("in_part") is not None
        (superseded_by_in_part if in_part else superseded_by).update(
            _numbers(match.group("numbers"))
        )
    supersedes: set[str] = set()
    supersedes_in_part: set[str] = set()
    for found in _SUPERSEDES.finditer(status_text):
        clause = _clause(status_text, found.start(), found.end())
        (supersedes_in_part if _IN_PART.search(clause) else supersedes).update(_numbers(clause))
    return Decision(
        number=title.group(1),
        title=title.group(2),
        status=status_text,
        filename=path.name,
        superseded_by=frozenset(superseded_by),
        superseded_by_in_part=frozenset(superseded_by_in_part),
        supersedes=frozenset(supersedes),
        supersedes_in_part=frozenset(supersedes_in_part),
    )


def _clause(text: str, keyword_start: int, start: int) -> str:
    """The text after a 'supersedes' up to the end of its clause.

    A clause ends at ';', at a '.' followed by whitespace (a dot inside `code` or "0042." at the
    end is not a break), or at the ')' that closes a '(' opened before the keyword. Brackets
    opened inside the clause are balanced first, so "the `f(x)` clause of 0001" stays whole.
    """
    opened_before = text.count("(", 0, keyword_start) > text.count(")", 0, keyword_start)
    inner = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            inner += 1
        elif char == ")":
            if inner == 0 and opened_before:
                return text[start:index]
            inner = max(inner - 1, 0)
        elif char == ";" or (char == "." and text[index + 1 : index + 2].isspace()):
            return text[start:index]
    return text[start:]


def _numbers(text: str) -> list[str]:
    return _NUMBER.findall(text)


def load_decisions(directory: Path) -> list[Decision]:
    """Every NNNN-*.md in the directory, by number; other files are skipped."""
    decisions = [parse_decision(p) for p in sorted(directory.glob("*.md")) if _FILE.match(p.name)]
    seen: dict[str, str] = {}
    for decision in decisions:
        if decision.number in seen:
            msg = f"{decision.filename}: number {decision.number} is also {seen[decision.number]}"
            raise DecisionFormatError(msg)
        seen[decision.number] = decision.filename
    return sorted(decisions, key=lambda d: d.number)


def _superseded_by_cell(decision: Decision, everyone: list[Decision]) -> str:
    """The records that replace this one, from its own Status line and from the others' lines.

    A replacement is shown plain only when this record's own status is "superseded" and no line
    calls it partial ("in part", "partly"); any other is "(in part)", because the record still
    stands apart from the part that was replaced.
    """
    gone = decision.keyword == "superseded"
    partial: dict[str, bool] = {}

    def note(number: str, *, in_part: bool) -> None:
        partial[number] = partial.get(number, False) or in_part or not gone

    for number in decision.superseded_by:
        note(number, in_part=False)
    for number in decision.superseded_by_in_part:
        note(number, in_part=True)
    for other in everyone:
        if decision.number in other.supersedes:
            note(other.number, in_part=False)
        if decision.number in other.supersedes_in_part:
            note(other.number, in_part=True)
    return ", ".join(f"{n} (in part)" if partial[n] else n for n in sorted(partial))


def build_index(directory: Path) -> str:
    """Render the index for the records in `directory`."""
    decisions = load_decisions(directory)
    lines = [
        "# Decision index",
        "",
        "Generated by `mise run gen:build` from `docs/decisions/`. Do not edit.",
        "",
        "| Number | Title | Status | Superseded by |",
        "|---|---|---|---|",
    ]
    for decision in decisions:
        title = decision.title.replace("|", "\\|")
        link = f"[{title}](../decisions/{decision.filename})"
        row = [decision.number, link, decision.keyword, _superseded_by_cell(decision, decisions)]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """Entry point; returns the process exit code."""
    try:
        expected = build_index(DECISIONS_DIR)
    except DecisionFormatError as exc:
        print(f"gen_decision_index: {exc}", file=sys.stderr)
        return 1
    if "--check" in argv:
        if not INDEX_PATH.exists() or INDEX_PATH.read_bytes() != expected.encode():
            print(f"stale or missing: {INDEX_PATH}\nRun: mise run gen:build", file=sys.stderr)
            return 1
        return 0
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_bytes(expected.encode())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
