"""Redaction must not destroy agenda content (decision 0280), and must still mask real secrets.

The first block is text that must come back unchanged: dates, times, course codes, versions, grades
and file names. The second is text with a real secret that must still be masked.
"""

import time

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from command_center.core.redact import redact

_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

REQUIRED_KEEP = [
    "Dentist appointment 11/12/2026 3:00 PM",
    "Exam 11/12 10:30 AM",
    "Weekly 1:1 11/10 2:00 PM",
    "2026-11-12 3:00 PM",
    "CS 2420-001",
    "MATH 1210-003",
    "Semester 2026-2027",
    "FY 2026/27",
    "GPA 3.85/4.00",
    "Release 2.4.1.7",
    "Python 3.13.1",
    "Essay_Draft_v2_FINAL_final.docx",
    "Internationalization_and_Localization_Review",
]

# Thirty more realistic lines: class names, meetings, deadlines, prices, version numbers and file
# names, none of them holding a secret.
AGENDA_KEEP = [
    "Nov 12, 2026 10:30 AM dentist",
    "Final exam 12/14/2026 8:00-10:00 AM",
    "Due 11/12/2026 11:59 PM MST",
    "CS 2420 code review with Priya",
    "PHYS 2210/2215 Physics for Scientists",
    "Academic year 2026-27 advising",
    "Scored 92.5/100 on quiz 3",
    "Rent due $1,250.00 on 11/30",
    "Pay tuition $4,830.50 by 12/01/2026",
    "Flight UA 1234 SLC to DEN 7:45 AM",
    "Lab 3.2 prelab and Problem 4.17 on HW 9",
    "Weekend trip 11/20-11/22",
    "Conference 2026-12-05 to 2026-12-07",
    "Team standup 9:00 - 9:15 daily",
    "Sprint review 2026-11-20 2:00 PM",
    "Math 1210 exam 2 (chapters 4-6)",
    "Budget FY2026-27 planning",
    "Staff meeting 12/5-12/7",
    "Office hours 2:00-3:30 pm Room 2031 ESB",
    "Quiz 3 grade: 18/20, class average 78.4",
    "Lecture 12: Dynamic programming (Sec 15.1-15.4)",
    "Anthropomorphization_of_Electromechanical_Systems_Lecture_Notes",
    "lab_report_week_10_thermodynamics_final_version.pdf",
    "meeting-notes-2026-11-10-team-standup-agenda-and-action-items.md",
    "Standup moved to 10:30 on 11/12 (Thursday)",
    "Upgrade to Node 26.13.0 and Version 1.2.3.4 release notes",
    "Lunch @ noon with Sam, dinner @ 6:30 PM",
    "Password manager workshop Fri 11/13 3:00 PM",
    "Verify enrollment with registrar by 2026-11-20",
    "Token economy lecture notes for PSY 1010",
]


def test_the_agenda_corpus_has_thirty_extra_lines() -> None:
    assert len(AGENDA_KEEP) == 30


@pytest.mark.parametrize("text", REQUIRED_KEEP)
def test_redact_keeps_the_required_agenda_lines_unchanged(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize("text", AGENDA_KEEP)
def test_redact_keeps_realistic_agenda_lines_unchanged(text: str) -> None:
    assert redact(text) == text


SECRET_LINES = [
    ("Reset link: https://example.com/reset?token=abc123", "Reset link: [url]"),
    ("feed ftp://user:pw@host.example.net/cal.ics", "feed [url]"),
    ("see s3://my-bucket/exports/2026.csv", "see [url]"),
    ("db postgres://admin:hunter2@10.0.0.5:5432/prod", "db [url]"),
    ("admin panel 192.168.1.20/admin?key=x", "admin panel [url]"),
    ("dev server localhost:8080/api/session?x=1", "dev server [url]"),
    ("router at 10.0.0.1 is down", "router at [ip] is down"),
    ("Your password is 4821", "Your password is [number]"),
    ("passwd 12345 expires", "passwd [number] expires"),
    ("token: 48213", "token: [number]"),
    ("verify with 4821 now", "verify with [number] now"),
    ("card cvv 123 exp 11/28", "card cvv [number] exp 11/28"),
    ("4821 is your verification code", "[number] is your verification code"),
    ("call 801,555,1234 today", "call [number] today"),
    ("call 801*555*1234 today", "call [number] today"),
    ("call 801x555x1234 today", "call [number] today"),
    ("mail bob @ example.com please", "mail [email] please"),
    ("mail bob{at}example{dot}com please", "mail [email] please"),
    ("key AKIAIOSFODNN7EXAMPLE", "key [token]"),
    ("secret wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "secret [token]"),
]


def test_the_secret_corpus_has_twenty_lines() -> None:
    assert len(SECRET_LINES) == 20


@pytest.mark.parametrize(("text", "expected"), SECRET_LINES)
def test_redact_still_masks_real_secrets(text: str, expected: str) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("call 801-555-1234 now", "call [number] now"),
        ("order 123456", "order [number]"),
        ("11/12 and card 4111 1111 1111 1111", "11/12 and card [number]"),
        ("12/12/2026 8015551234", "12/12/2026 [number]"),
        ("12/12/2026-8015551234", "[number]"),
        ("2026 10:30 801 555 1234", "2026 10:[number]"),
        ("1/2/3/4/5/6", "[number]"),
        ("801 555 1234 3:00 PM", "[number] 3:00 PM"),
        ("CS 2420-001 8015551234", "CS 2420-001 [number]"),
        ("x 2420-001 y", "x [number] y"),
        ("2420-0019", "[number]"),
        ("2026-2027-2028 5551234", "[number]"),
        ("10.0.0.1", "[ip]"),
        ("192.168.1.20", "[ip]"),
        ("server 192.168.100.200 up", "server [ip] up"),
        ("1.1.1.1 2", "[ip] 2"),
    ],
)
def test_redact_keeps_dates_and_times_but_masks_phone_like_runs_next_to_them(
    text: str, expected: str
) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("version 2.4.10.17 notes", "version 2.4.10.17 notes"),
        ("v2.4.10.17", "v2.4.10.17"),
        ("Build: 1.2.3.4", "Build: 1.2.3.4"),
        ("rev 1.2.3.4", "rev 1.2.3.4"),
        ("IP 1.2.3.4", "IP [ip]"),
        ("1.2.3.4", "[ip]"),
        ("reversion 1.2.3.4", "reversion [ip]"),
        ("release 2.4.1.7 on 10.0.0.1", "release 2.4.1.7 on [ip]"),
    ],
)
def test_redact_keeps_a_four_part_version_after_a_version_word_only(
    text: str, expected: str
) -> None:
    assert redact(text) == expected


_PHRASE_KEPT = [
    "Essay_Draft_v2_FINAL_final",
    "Internationalization_and_Localization_Review",
    "Quarterly-Business-Review-Deck-Final-2026",
    "meeting_notes_for_the_2026_budget_review",
    "iPhone_Setup_Guide_Version_2_Final_Draft",
    "Another_Long_Draft_v2_FINAL_final_copy_v3",
]
_TOKEN_MASKED = [
    "550e8400-e29b-41d4-a716-446655440000",
    "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
    "kJhGfDsAq_WeRtYuIo_PlMnBvCxZ_aSdFgHjKl",
    "Abcdefghijklmnopqrstuvwx1_Abcdefghi",
    "a1-b2-c3-d4-e5-f6-g7-h8-i9-j0-k1-l2",
    "abcdefghijklmnopqrstuvwxyzabcdefghij",
    "Essay_Draft_v2_FINAL_final_9f8e7d6c5b",
]


@pytest.mark.parametrize("text", _PHRASE_KEPT)
def test_redact_keeps_words_joined_by_underscores_or_dashes(text: str) -> None:
    assert redact(f"see {text} now") == f"see {text} now"


_PHRASE_EDGES = [
    "Internationalization_Localization",
    "Cat_Dog_v2_v3_v4_v5_v6_v7_v8_v9_v10_v11",
    "Essay_GitHubActions_Notes_Final_Draft_Review",
]


@pytest.mark.parametrize("text", _PHRASE_EDGES)
def test_redact_keeps_a_phrase_at_the_edge_of_each_phrase_limit(text: str) -> None:
    assert redact(f"see {text} now") == f"see {text} now"


def test_redact_masks_a_run_with_a_piece_of_three_case_flips() -> None:
    assert redact("see Essay_aBcDeFgHi_Notes_Final_Draft_Review_x now") == "see [token] now"


@pytest.mark.parametrize("text", _TOKEN_MASKED)
def test_redact_masks_a_key_shaped_run_even_with_separators(text: str) -> None:
    assert redact(f"key {text} end") == "key [token] end"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CS 2420 code review", "CS 2420 code review"),
        ("Verify PSY 1010 enrollment", "Verify PSY 1010 enrollment"),
        ("Your PIN 4821", "Your PIN [number]"),
        ("Your code is 4821", "Your code is [number]"),
        ("Use 4821 as your login code", "Use [number] as your login code"),
        ("cs 2420 code review", "cs [number] code review"),
        ("CS2420 code review", "CS2420 code review"),
        ("Use 4821 for your token", "Use [number] for your token"),
        ("2026-11-09 code", "2026-11-09 code"),
        ("code;4821", "code;[number]"),
        ("cvc 4821", "cvc [number]"),
        ("cvv2: 123", "cvv2: [number]"),
        ("the cvv", "the cvv"),
        ("passcodes 48213 and 99107", "passcodes [number] and [number]"),
    ],
)
def test_redact_masks_a_code_next_to_its_keyword_but_not_a_course_number(
    text: str, expected: str
) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("call 1,234,567 times", "call 1,234,567 times"),
        ("budget $1,234,567", "budget $1,234,567"),
        ("1,801,555,1234 units", "1,801,555,1234 units"),
        ("rooms 101,102,103", "rooms 101,102,103"),
        ("call 801,555,1234", "call [number]"),
        ("801*555*1234", "[number]"),
        ("801x555x1234", "[number]"),
        ("801,555*1234", "[number]"),
        ("Annex801x555x1234", "Annex801x555x1234"),
        ("801,555,12345", "801,555,12345"),
    ],
)
def test_redact_joins_a_phone_with_comma_star_or_x_only_in_the_three_three_four_shape(
    text: str, expected: str
) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("bob @ example.com", "[email]"),
        ("bob@ example.com", "[email]"),
        ("bob @example.com", "[email]"),
        ("write bob @ mail.example.co.uk now", "write [email] now"),
        ("bob{at}example.com", "[email]"),
        ("bob {at} example {dot} com", "[email]"),
        ("bob(at)example{dot}com", "[email]"),
        ("Lunch @ noon", "Lunch @ noon"),
        ("Meet @ 3.30pm", "Meet @ 3.30pm"),
        ("Standup @ Room 12", "Standup @ Room 12"),
    ],
)
def test_redact_masks_a_spaced_or_braced_email_but_not_an_at_sign_in_a_sentence(
    text: str, expected: str
) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("HTTP://EXAMPLE.COM/x", "[url]"),
        ("ssh://git@host.example/repo.git", "[url]"),
        ("jdbc:postgresql://db.local/app", "jdbc:[url]"),
        ("git+https://host.example/r.git", "[url]"),
        ("localhost/admin", "[url]"),
        ("localhost:3000?debug=1", "[url]"),
        ("127.0.0.1:8000/x", "[url]"),
        ("10.0.0.0/24 subnet", "[url] subnet"),
        ("see localhost for details", "see localhost for details"),
        ("v1.2.3.4/x", "v1.2.3.4/x"),
        ("a://", "a://"),
        ("1x://y", "1[url]"),
    ],
)
def test_redact_masks_any_url_scheme_and_a_local_host_followed_by_a_path(
    text: str, expected: str
) -> None:
    assert redact(text) == expected


_KNOWN_GAPS = [
    "bob at example dot com",
    "801:555:1234",
]


@pytest.mark.parametrize("text", _KNOWN_GAPS)
def test_redact_leaves_the_recorded_known_gaps_as_typed(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "1231123::1::",
        "12345610:30::1",
        "[number]:30::1",
        "111112ff::1::",
        "::a.2026-11-092026-11-09",
        "801,555,1234,11/1211/12",
    ],
)
def test_redact_is_idempotent_on_a_run_that_starts_after_a_marker_and_a_colon(text: str) -> None:
    once = redact(text)

    assert redact(once) == once


_PARTS = st.sampled_from(
    [
        *("1", "12", "345", "610", "7", "30", "::", ":", "1::", "ff", "a", ".", " "),
        *("[number]", "[ip]", "2026-11-09", ",", "801,555,1234", "11/12"),
    ]
)


@example("1231123::1::")
@example("12345610:30::1")
@given(st.lists(_PARTS, max_size=14).map("".join))
def test_redact_is_idempotent_on_digits_colons_and_markers(text: str) -> None:
    once = redact(text)

    assert redact(once) == once


_AGENDA_PIECES = st.sampled_from(
    [
        "11/12", "11/12/2026", "2026-11-12", "10:30", "3:00", "PM", "CS", "2420-001", "2026-2027",
        "3.85/4.00", "2.4.1.7", "Release", "code", "pin", "4821", " ", " ", " ", "-", "/", ",",
        "801,555,1234", "bob @ a.com", "{at}", "Essay_Draft_v2_FINAL", "localhost/x", "1.2.3.4",
    ]
)  # fmt: skip


@given(st.lists(_AGENDA_PIECES, max_size=14).map("".join))
def test_redact_is_idempotent_on_agenda_pieces(text: str) -> None:
    once = redact(text)

    assert redact(once) == once


# Tests that kill mutants of the length bounds in redact.py (decision 0280).
@pytest.mark.parametrize(
    ("prefix", "minimum"), [("ghp_", 16), ("ghs_", 16), ("github_pat_", 16), ("AIza", 20)]
)
def test_redact_masks_a_known_prefix_key_at_its_minimum_length_and_not_below(
    prefix: str, minimum: int
) -> None:
    assert redact(f"key {prefix}{_LETTERS[:minimum]} end") == "key [token] end"
    below = f"key {prefix}{_LETTERS[: minimum - 1]} end"
    assert redact(below) == below


def test_redact_masks_an_ipv6_address_of_the_longest_text_form() -> None:
    longest = "0000:0000:0000:0000:0000:ffff:255.255.255.255"

    assert len(longest) == 45
    assert redact(f"at {longest} now") == "at [ip] now"


def test_redact_does_not_read_a_run_over_45_characters_as_an_address() -> None:
    too_long = "0000:0000:0000:0000:0000:ffff:255.255.255.255:1"

    assert redact(f"at {too_long} now") != "at [ip] now"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("see www.example.com:65535/x now", "see [url] now"),
        ("see example.com:65535/x now", "see [url] now"),
        ("see example.com:123456/x now", "see example.com:[number]/x now"),
        ("see example.com:1/x now", "see [url] now"),
    ],
)
def test_redact_reads_a_port_of_one_to_five_digits_in_a_scheme_less_url(
    text: str, expected: str
) -> None:
    assert redact(text) == expected


def test_redact_reads_a_host_label_of_63_characters_and_not_64() -> None:
    label = "a-" * 31 + "a"

    assert len(label) == 63
    assert redact(f"see {label}.com/x now") == "see [url] now"
    too_long = "a-" * 31 + "ab"
    assert len(too_long) == 64
    assert redact(f"see {too_long}.com/x now") != "see [url] now"


@pytest.mark.parametrize(
    ("tld", "expected"),
    [
        ("c", "see example.c/x now"),
        ("co", "see [url] now"),
        ("a" * 24, "see [url] now"),
        ("a" * 25, f"see example.{'a' * 25}/x now"),
    ],
)
def test_redact_reads_a_tld_of_two_to_24_letters(tld: str, expected: str) -> None:
    assert redact(f"see example.{tld}/x now") == expected


@pytest.mark.parametrize("gap", [";", "|", "&", ">"])
def test_redact_masks_a_code_after_each_of_these_gap_characters(gap: str) -> None:
    assert redact(f"code{gap}4821") == f"code{gap}[number]"


@pytest.mark.parametrize(
    ("text", "expected"),
    [(":fe80::1", ":[ip]"), ("x :fe80::1 y", "x :[ip] y"), (":::1", ":::1"), ("::1", "[ip]")],
)
def test_redact_drops_one_leading_colon_from_an_address(text: str, expected: str) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PASSWD 4821", "PASSWD [number]"),
        ("VERIFY 4821", "VERIFY [number]"),
        ("OTPS 4821", "OTPS [number]"),
        ("pin 4821-993", "pin [number]"),
        ("code 1234/5678", "code [number]"),
        ("1.https://zoom.us/j/123?pwd=x", "1.[url]"),
        ("2https://x.io/a", "2[url]"),
        ("+https://x.io/a b", "+[url] b"),
        ("see 2020-11-10https://x.io/a", "see 2020-11-10[url]"),
        ("CS 2420-001", "CS 2420-001"),
    ],
)
def test_redact_review_findings_keyword_prefixes_and_schemes_after_digits(
    text: str, expected: str
) -> None:
    assert redact(text) == expected
    assert redact(expected) == expected


@pytest.mark.parametrize("text", ["1" * 200_000, "1a" * 100_000, "-" * 200_000, "1.a" * 70_000])
def test_redact_scheme_prefix_scan_is_linear(text: str) -> None:
    started = time.perf_counter()
    redact(text)

    assert time.perf_counter() - started < 5.0
