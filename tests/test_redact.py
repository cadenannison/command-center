"""Redaction and trimming for summary input."""

import re
import time
from datetime import date

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from command_center.core.redact import (
    _EMAIL,  # pyright: ignore[reportPrivateUsage]
    redact,
    trim,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail jane.doe+x@school.edu now", "mail [email] now"),
        ("a@b.co and c@d.org", "[email] and [email]"),
        ("call 8015551234 today", "call [number] today"),
        ("order 123456", "order [number]"),
        ("room 12345 ok", "room 12345 ok"),
        ("CS 101 midterm", "CS 101 midterm"),
        ("id 12345678901234567890", "id [number]"),
        ("user42@x.io 9876543", "[email] [number]"),
        ("", ""),
    ],
)
def test_redact_replaces_emails_and_long_digit_runs(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_redact_leaves_plain_text_alone() -> None:
    assert redact("Physics homework due Friday") == "Physics homework due Friday"


def test_redact_strips_non_ascii_digit_runs() -> None:
    assert redact("code ١٢٣٤٥٦") == "code [number]"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("call 801-555-1234 now", "call [number] now"),
        ("call (801) 555 1234 now", "call [number] now"),
        ("call (801)555-1234", "call [number]"),
        ("call 801.555.1234.", "call [number]."),
        ("card 4111 1111 1111 1111 ok", "card [number] ok"),
        ("card 4111-1111-1111-1111", "card [number]"),
        ("12 34 56", "[number]"),
        ("1 2 3 4 5 6", "[number]"),
        ("id 123 456", "id [number]"),
        ("call (8015551234)", "call ([number])"),
        ("[number] 801-555-1234", "[number] [number]"),
        ("a@b.co 801-555-1234", "[email] [number]"),
    ],
)
def test_redact_replaces_digit_groups_joined_by_separators(text: str, expected: str) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "room 12-34",
        "CS 101 and 202",
        "version 1.2.3",
        "(80) 555",
        "1234 5",
        "Quiz 3 - Chapter 12",
        "due 11-07",
    ],
)
def test_redact_keeps_digit_groups_with_fewer_than_six_digits(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "due 2026-11-07",
        "due 2026-11-07.",
        "due (2026-11-07)",
        "2026-11-07 and 2026-11-08",
        "2026-11-07 5",
        "5 2026-11-07",
        "on 2026-11-07, 2026-12-01",
    ],
)
def test_redact_keeps_standalone_iso_dates(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("20261107", "[number]"),
        ("2026-11-07-1234", "[number]"),
        ("1234-2026-11-07", "[number]"),
        ("2026-11-07.5", "[number]"),
        ("2026.11.07", "[number]"),
        ("2026 11 07", "[number]"),
        ("2026-13-07", "[number]"),
        ("2026-11-32", "[number]"),
        ("5-2026-11-07", "[number]"),
        ("801 2026-11-07-5", "[number]"),
        ("12026-11-07", "[number]"),
        ("2026-11-071", "[number]"),
        ("2026-11-07 8015551234", "2026-11-07 [number]"),
        ("2026-11-07 555-1234", "2026-11-07 [number]"),
        ("801 555 2026-11-07", "[number] 2026-11-07"),
        ("(801) 555 2026-11-07", "[number] 2026-11-07"),
    ],
)
def test_redact_does_not_let_the_iso_date_exemption_hide_digits(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_redact_keeps_surrounding_words_and_markers_intact() -> None:
    assert redact("see [email] or [number] re 801-555-1234 (urgent)") == (
        "see [email] or [number] re [number] (urgent)"
    )


_ISO = r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
_YEAR_RANGE = r"(?:19|20)[0-9]{2}[-–/](?:(?:19|20)[0-9]{2}|[0-9]{2})"  # noqa: RUF001
_YEAR_MONTH = r"[0-9]{4}-(?:0[1-9]|1[0-2])-"
_GROUP = re.compile(r"\d(?:[\s().\-]*\d)*")


def _digit_groups_outside_iso_dates(text: str) -> list[str]:
    # A date is exempt when whitespace or the edge of its digit group bounds it on both sides,
    # whatever the text around that group is (so "due 2026-11-07." and "x2026-11-07" count).
    # Decision 0280 also keeps a year range ("2026-2027", "2026/27") and the date part left in front
    # of a marker when a later rule masked the tail ("2000-01-[ip]").
    kept = rf"(?<!\S)(?:{_ISO}(?!\S)|{_YEAR_RANGE}(?!\S)|{_YEAR_MONTH}(?=\[))"
    masked = _GROUP.sub(lambda m: re.sub(kept, "|", m.group()), text)
    return [g for g in _GROUP.findall(masked) if sum(c.isdigit() for c in g) >= 6]


# Explicit expectations, so the test does not rebuild the implementation's own rule. A dotted quad
# is an address, not a number (decisions 0244, 0255); other digit groups of six or more digits are
# numbers (decision 0280 keeps dates, versions and section ranges, which no example here is).
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("x 10.0.0.1 y", "x [ip] y"),
        ("x 192.168.1.20 y", "x [ip] y"),
        ("x 1.1.1.1 2 y", "x [ip] 2 y"),
        ("x 0.0.0.0 y", "x [ip] y"),
        ("x 255.255.255.255 y", "x [ip] y"),
        ("x 123.456.789 y", "x [number] y"),
        ("x 1 2 3 4 5 6 y", "x [number] y"),
        ("x 12-34-56 y", "x [number] y"),
        ("x 123456 y", "x [number] y"),
        ("x 12345 y", "x 12345 y"),
        ("x 1 2 3 4 5 y", "x 1 2 3 4 5 y"),
        ("x 123 456 y", "x [number] y"),
        ("x 123 45 y", "x 123 45 y"),
    ],
)
def test_redact_marks_dotted_quads_as_addresses_and_long_digit_groups_as_numbers(
    text: str, expected: str
) -> None:
    assert redact(text) == expected


_CHUNKS = st.text(alphabet="0123456789", min_size=1, max_size=3)
# Two separator sets that cannot form a date, a section range ("1.2-3.4") or a dotted quad: dashes
# and spaces with any number of chunks, or dots and spaces with at most three chunks.
_DASHED = st.lists(st.sampled_from([" ", "-", ") ", "  ", " - "]), min_size=12, max_size=12)
_DOTTED = st.lists(st.sampled_from([" ", ".", ") ", "  "]), min_size=12, max_size=12)


@given(
    chunks=st.lists(_CHUNKS, min_size=2, max_size=12),
    separators=_DASHED,
)
def test_redact_replaces_any_dash_or_space_joined_number_of_six_or_more_digits(
    chunks: list[str], separators: list[str]
) -> None:
    number = chunks[0] + "".join(
        sep + chunk for sep, chunk in zip(separators, chunks[1:], strict=False)
    )
    digits = sum(len(c) for c in chunks)
    assert redact(f"x {number} y") == (f"x {'[number]' if digits >= 6 else number} y")


@given(
    chunks=st.lists(_CHUNKS, min_size=2, max_size=3),
    separators=_DOTTED,
)
def test_redact_replaces_any_dot_or_space_joined_number_of_six_or_more_digits(
    chunks: list[str], separators: list[str]
) -> None:
    number = chunks[0] + "".join(
        sep + chunk for sep, chunk in zip(separators, chunks[1:], strict=False)
    )
    digits = sum(len(c) for c in chunks)
    assert redact(f"x {number} y") == (f"x {'[number]' if digits >= 6 else number} y")


@example("call 801-555-1234")
@example("a 2026-11-07 555-1234")
@example("due 2026-11-07.")
@example("on 2026-11-07, 2026-12-01")
@example("x2026-11-07 123456")
@given(st.text())
def test_redact_leaves_no_group_of_six_digits_outside_standalone_iso_dates(
    text: str,
) -> None:
    assert _digit_groups_outside_iso_dates(redact(text)) == []


_ISO_DATES = st.dates(min_value=date(1, 1, 1), max_value=date(9999, 12, 31)).map(date.isoformat)
_PIECES = st.one_of(
    _ISO_DATES,
    st.text(alphabet="0123456789", min_size=1, max_size=8),
    st.sampled_from(
        [" ", "  ", "\n", "-", ".", ",", "(", ")", ") ", " (", "x", "due ", "@", "a@b"]
    ),
    st.text(max_size=4),
)


@given(st.lists(_PIECES, max_size=14).map("".join))
def test_redact_leaves_no_group_of_six_digits_outside_iso_dates_in_date_heavy_text(
    text: str,
) -> None:
    assert _digit_groups_outside_iso_dates(redact(text)) == []


@given(_ISO_DATES, st.text(alphabet="abc ", max_size=6), st.text(alphabet="abc ", max_size=6))
def test_redact_keeps_an_iso_date_set_off_by_whitespace(day: str, before: str, after: str) -> None:
    text = f"{before}\t{day}\n{after}"

    assert day in redact(text)


@given(st.text())
def test_redact_is_idempotent(text: str) -> None:
    once = redact(text)

    assert redact(once) == once


@given(st.text(), st.emails(), st.integers(min_value=100000, max_value=10**15))
def test_redact_never_leaks_embedded_email_or_number(text: str, email: str, number: int) -> None:
    result = redact(f"{text} {email} {number} {text}")

    assert email not in result
    assert str(number) not in result


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("short", 10, "short"),
        ("exactly10!", 10, "exactly10!"),
        ("this is far too long", 10, "this is f…"),
        ("  padded  ", 20, "padded"),
        ("abc", 0, ""),
        ("abc", 1, "…"),
    ],
)
def test_trim_caps_length_with_an_ellipsis(text: str, limit: int, expected: str) -> None:
    assert trim(text, limit) == expected


def test_trim_rejects_negative_limit() -> None:
    with pytest.raises(ValueError, match="limit"):
        trim("abc", -1)


@given(st.text(), st.integers(min_value=0, max_value=200))
def test_trim_never_exceeds_limit(text: str, limit: int) -> None:
    assert len(trim(text, limit)) <= limit


@given(st.text(), st.integers(min_value=0, max_value=200))
def test_trim_is_idempotent(text: str, limit: int) -> None:
    once = trim(text, limit)

    assert trim(once, limit) == once


_OLD_EMAIL = re.compile(r"\S+@\S+")
_EMAIL_ALPHABET = st.sampled_from(["a", "b", "@", " ", "\n", "\t", ".", "-", "(", "1", "\u00a0"])


@given(st.text(alphabet=_EMAIL_ALPHABET) | st.text())
def test_email_pattern_matches_exactly_what_the_unanchored_pattern_matched(text: str) -> None:
    assert [m.span() for m in _EMAIL.finditer(text)] == [
        m.span() for m in _OLD_EMAIL.finditer(text)
    ]


_LONG = 100_000
_TIME_BUDGET_SECONDS = 5.0


@pytest.mark.parametrize(
    "text",
    [
        "a" * (2 * _LONG),
        "a@" * _LONG,
        "@" * (2 * _LONG),
        "1 " * _LONG,
        "1-" * _LONG,
        "1." * _LONG,
        "(" * (2 * _LONG),
        "1(" * _LONG,
        "1" + " " * (2 * _LONG) + "x",
        "1" + ")" * (2 * _LONG) + "x",
        "2026-11-07 " * (_LONG // 5),
        "2026-11-07-" * (_LONG // 5),
    ],
    ids=[
        "no-space-run",
        "at-signs-in-one-token",
        "only-at-signs",
        "digit-space",
        "digit-dash",
        "digit-dot",
        "open-parens",
        "digit-paren",
        "digit-then-spaces",
        "digit-then-close-parens",
        "spaced-dates",
        "dashed-dates",
    ],
)
def test_redact_finishes_quickly_on_long_adversarial_input(text: str) -> None:
    started = time.perf_counter()
    redact(text)

    assert time.perf_counter() - started < _TIME_BUDGET_SECONDS
