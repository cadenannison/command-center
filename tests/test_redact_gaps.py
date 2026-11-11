"""Gaps found in a review of core/redact.py: one row per case (decisions 0240-0244)."""

# ruff: noqa: RUF001  (the inputs are deliberate look-alike characters: fullwidth, en dash, NBSP)

import time
import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st

from command_center.core.redact import redact

_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_JWT_PARTS = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ",
    "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
)
_SHORT_JWT = ("eyJhbGciOiJub25lIn0", "eyJzdWIiOiIxIn0")

# (text, the sensitive substring that must not survive, one row per leak found in the review).
_LEAKS = [
    # 4-5 digit codes after a keyword
    pytest.param("Your code: 48213", "48213", id="code-colon"),
    pytest.param("Your code is 48213 today", "48213", id="code-is"),
    pytest.param("CODE 4821", "4821", id="code-uppercase"),
    pytest.param("OTP 4821", "4821", id="otp"),
    pytest.param("otp: 482193", "482193", id="otp-six-digits"),
    pytest.param("Your PIN is 1234", "1234", id="pin-is"),
    pytest.param("pin 54321", "54321", id="pin-five-digits"),
    pytest.param("passcode: 9876", "9876", id="passcode"),
    pytest.param("Verification: 4821", "4821", id="verification-colon"),
    pytest.param("verification code for your account is 12345", "12345", id="verification-words"),
    pytest.param("Codes: 4821", "4821", id="codes-plural"),
    # scheme-less URLs
    pytest.param("reset at example.com/reset?token=abcdef", "abcdef", id="schemeless-token"),
    pytest.param("reset at example.com/reset?token=abcdef", "example.com", id="schemeless-host"),
    pytest.param("see www.x.com/path?k=secret now", "secret", id="www-path"),
    pytest.param("see www.example.com now", "www.example.com", id="www-bare"),
    pytest.param("feed WWW.Example.COM/Feed?T=abc", "Feed", id="www-uppercase"),
    pytest.param("open sub.school.edu:8080/a?b=c ok", "school.edu", id="schemeless-port"),
    pytest.param("open school.edu/x#frag ok", "school.edu", id="schemeless-fragment"),
    # known provider keys
    pytest.param("key AKIAIOSFODNN7EXAMPLE end", "AKIAIOSFODNN7EXAMPLE", id="aws-akia"),
    pytest.param("key ghp_" + _LETTERS[:36] + " end", _LETTERS[:36], id="github-ghp-letters"),
    pytest.param("key gho_" + _LETTERS[:36] + " end", _LETTERS[:36], id="github-gho"),
    pytest.param("key ghu_" + _LETTERS[:36] + " end", _LETTERS[:36], id="github-ghu"),
    pytest.param("key ghs_" + _LETTERS[:36] + " end", _LETTERS[:36], id="github-ghs"),
    pytest.param("key github_pat_" + "A" * 22 + "_" + "b" * 10, "A" * 22, id="github-pat"),
    pytest.param("key sk-" + _LETTERS[:30] + " end", _LETTERS[:30], id="sk-letters"),
    pytest.param("key sk-ant-api-" + "x" * 20 + " end", "x" * 20, id="sk-hyphenated"),
    pytest.param("key xoxb-abcdefghij end", "abcdefghij", id="slack-xoxb"),
    pytest.param("key xoxp-abcdefghij end", "abcdefghij", id="slack-xoxp"),
    # xoxa- and xoxr- are split so the secret scanner does not read them as real Slack tokens
    pytest.param("key xo" + "xa-abcdefghij end", "abcdefghij", id="slack-xoxa"),
    pytest.param("key xo" + "xr-abcdefghij end", "abcdefghij", id="slack-xoxr"),
    pytest.param("key xoxs-abcdefghij end", "abcdefghij", id="slack-xoxs"),
    pytest.param("key AIza" + _LETTERS[:35] + " end", _LETTERS[:35], id="google-aiza"),
    # 32+ characters, digit or not
    pytest.param("tok " + "a" * 32 + " end", "a" * 32, id="letters-only-32"),
    pytest.param("tok " + _LETTERS[:40] + " end", _LETTERS[:40], id="mixed-case-letters-40"),
    pytest.param("tok " + "ab-" * 11 + "ab end", "ab-ab-ab", id="hyphenated-letters-only"),
    pytest.param(
        "tok " + _LETTERS[:30] + "+/=" + _LETTERS[:6], _LETTERS[:30], id="base64-no-digit"
    ),
    pytest.param("tok " + _LETTERS[:35] + "=", _LETTERS[:35], id="base64-padding-no-digit"),
    pytest.param("tok " + _LETTERS[:20] + "+" + _LETTERS[:20] + " end", "+", id="plus-joined-40"),
    pytest.param("tok " + "a1" * 12 + " end", "a1a1a1", id="digit-token-24-still-masked"),
    # tokens split by "." or "/"
    pytest.param(".".join(_JWT_PARTS), _JWT_PARTS[0], id="jwt-header"),
    pytest.param(".".join(_JWT_PARTS), _JWT_PARTS[1], id="jwt-payload"),
    pytest.param(".".join(_JWT_PARTS), _JWT_PARTS[2], id="jwt-signature"),
    pytest.param("auth " + ".".join(_JWT_PARTS) + " ok", "dozjgNryP4J3", id="jwt-in-sentence"),
    pytest.param(".".join(_SHORT_JWT) + ".", _SHORT_JWT[0], id="jwt-alg-none-header"),
    pytest.param(".".join(_SHORT_JWT) + ".", _SHORT_JWT[1], id="jwt-alg-none-payload"),
    pytest.param("abc." + "x" * 32 + ".def", "abc.", id="dot-joined-head"),
    pytest.param("abc." + "x" * 32 + ".def", ".def", id="dot-joined-tail"),
    pytest.param("abc/" + "x" * 32 + "/def", "abc/", id="slash-joined-head"),
    pytest.param("abc/" + "x" * 32 + "/def", "/def", id="slash-joined-tail"),
    pytest.param("abc." + "a1" * 13 + ".def", "abc.", id="dot-joined-digit-token"),
    pytest.param("abc/" + "a1" * 13 + "/def", "/def", id="slash-joined-digit-token"),
    # phone numbers with other separators
    pytest.param("call 415/555/0132 now", "0132", id="phone-slash"),
    pytest.param("call 415–555–0132 now", "0132", id="phone-en-dash"),
    pytest.param("call 415—555—0132 now", "0132", id="phone-em-dash"),
    pytest.param("call 4_1_5_5_5_5_0_1_3_2 now", "0132", id="phone-underscore"),
    pytest.param("call 415_555_0132 now", "0132", id="phone-underscore-groups"),
    pytest.param("call 415 555 0132 now", "0132", id="phone-no-break-space"),
    pytest.param("call 415 555 0132 now", "0132", id="phone-narrow-no-break-space"),
    pytest.param("call 415‑555‑0132 now", "0132", id="phone-non-breaking-hyphen"),
    pytest.param("call ４１５ ５５５ ０１３２", "0132", id="phone-fullwidth"),
    # comma-grouped runs of 4-5 digits
    pytest.param("ref 12345,67890 ok", "67890", id="comma-two-five-digit-runs"),
    pytest.param("ref 12345,67890,13579 ok", "13579", id="comma-three-five-digit-runs"),
    pytest.param("card 4111,1111,1111,1111 ok", "1111", id="comma-card"),
    # IP addresses
    pytest.param("host 10.0.0.1 down", "10.0.0.1", id="ipv4-private"),
    pytest.param("host 192.168.1.100 down", "192.168.1.100", id="ipv4-lan"),
    pytest.param("dns 8.8.8.8.", "8.8.8.8", id="ipv4-sentence-end"),
    pytest.param("ping 10.0.0.1:8080 now", "10.0.0.1", id="ipv4-port"),
    pytest.param("ping 010.001.002.003 now", "010.001.002.003", id="ipv4-leading-zeros"),
    pytest.param("addr ::1 up", "::1", id="ipv6-loopback"),
    pytest.param("addr fe80::1 up", "fe80::1", id="ipv6-link-local"),
    pytest.param("addr 2001:db8::8a2e:370:7334 up", "2001:db8", id="ipv6-compressed"),
    pytest.param("addr 2001:0db8:85a3:0000:0000:8a2e:0370:7334 up", "85a3", id="ipv6-full"),
    pytest.param("addr [::1]:8080 up", "::1", id="ipv6-bracketed"),
    pytest.param("addr ::ffff:192.168.0.1 up", "192.168.0.1", id="ipv6-mapped-ipv4"),
    pytest.param("addr FE80::ABCD up", "ABCD", id="ipv6-uppercase"),
    pytest.param("addr fe80::1.", "fe80::1", id="ipv6-sentence-end"),
    # email spellings
    pytest.param("mail bob＠example.com now", "example.com", id="fullwidth-at"),
    pytest.param("mail bob [at] example [dot] com now", "bob", id="bracket-at-dot"),
    pytest.param("mail bob [at] example [dot] com now", "example", id="bracket-at-dot-domain"),
    pytest.param("mail bob(at)example(dot)com now", "bob", id="paren-at-dot-no-spaces"),
    pytest.param("mail bob (at) example (dot) com now", "example", id="paren-at-dot-spaces"),
    pytest.param("mail bob [AT] example [DOT] com now", "example", id="bracket-uppercase"),
    pytest.param("mail bob [at] example.com now", "example.com", id="bracket-at-real-dot"),
    pytest.param("mail bob [at] example [dot] co [dot] uk now", "uk", id="bracket-two-dots"),
    pytest.param("mail first.last [at] school [dot] edu", "first.last", id="bracket-dotted-local"),
    # reviewer round 1: scheme-less URLs after ":" or "-"
    pytest.param(
        "Reset link:example.com/reset?token=abcdef", "abcdef", id="schemeless-after-colon"
    ),
    pytest.param("URL:www.x.com/p?k=secret", "secret", id="www-after-colon"),
    pytest.param("go --example.com/p?k=secret now", "secret", id="schemeless-after-hyphens"),
    # base64 with digits and "/" but no "+" or "=", parts under 24 characters
    pytest.param(
        "key Ab3dEfGh1jKlMnOp/QrStUv2xYzAbCdEf/GhIj end", "QrStUv2xYzAbCdEf", id="b64-slash"
    ),
    pytest.param(
        "key wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY end", "bPxRfiCYEXAMPLEKEY", id="aws-secret"
    ),
    # IPv6 after a letter, a colon, and before a colon
    pytest.param("IPv6:2001:db8::1", "2001:db8", id="ipv6-after-label"),
    pytest.param("addr:fe80::1", "fe80::1", id="ipv6-after-colon"),
    pytest.param("mac:fe80::1 up", "fe80::1", id="ipv6-after-hex-letter-colon"),
    pytest.param("fe80::1: refused", "fe80::1", id="ipv6-trailing-colon"),
    pytest.param("peer 2001:db8::1: timed out", "2001:db8", id="ipv6-trailing-colon-long"),
    # invisible characters inside a secret
    pytest.param("call 801\u200b555\u200b1234 now", "1234", id="zero-width-space-phone"),
    pytest.param("call 801\u2060555\u20601234 now", "1234", id="word-joiner-phone"),
    pytest.param("call 801\ufeff555\ufeff1234 now", "1234", id="bom-phone"),
    pytest.param("key AKIA\u00adIOSFODNN7EXAMPLE end", "IOSFODNN7EXAMPLE", id="soft-hyphen-key"),
    pytest.param(
        "key ghp_\u200d" + _LETTERS[:36] + " end", _LETTERS[:36], id="zero-width-joiner-key"
    ),
    pytest.param("mail bob\u200b@example.com now", "example.com", id="zero-width-email"),
    # reviewer round 2: invisible default-ignorable characters and combining marks
    pytest.param("call 801\ufe0f555\ufe0f1234 now", "1234", id="variation-selector-phone"),
    pytest.param("call 801\u034f555\u034f1234 now", "1234", id="grapheme-joiner-phone"),
    pytest.param("call 801\u3164555\u31641234 now", "1234", id="hangul-filler-phone"),
    pytest.param("call 801\u180b555\u180b1234 now", "1234", id="mongolian-selector-phone"),
    pytest.param(
        "key AKIA\ufe0fIOSFODNN7EXAMPLE end", "IOSFODNN7EXAMPLE", id="variation-selector-key"
    ),
    # a second code inside the window of the same keyword
    pytest.param("backup codes 48213 and 99107", "99107", id="second-code-after-and"),
    pytest.param("codes 1111 2222 3333 4444 5555 6666 7777", "7777", id="code-chain"),
    pytest.param("PIN 1234, 5678, 9012", "9012", id="pin-comma-list"),
    # reviewer round 3: typographic separators around a code
    pytest.param("Your verification code \u2014 4821", "4821", id="code-em-dash"),
    pytest.param("code \u2013 4821", "4821", id="code-en-dash"),
    pytest.param("code \u201c4821\u201d", "4821", id="code-curly-quotes"),
    pytest.param("code \u00ab4821\u00bb", "4821", id="code-guillemets"),
    pytest.param("code: *4821*", "4821", id="code-asterisks"),
    pytest.param("code \u2192 4821", "4821", id="code-arrow"),
    pytest.param("codes 4821; 9910", "9910", id="codes-semicolon-list"),
    pytest.param("codes 48213 & 99107", "99107", id="codes-ampersand"),
    # reviewer round 3: a user's own "]" does not hide a URL or an address, a key after digits
    pytest.param("[EXTERNAL]www.bank.com/reset?t=ab12cd", "ab12cd", id="url-after-subject-tag"),
    pytest.param("[eth0]fe80::1", "fe80::1", id="ipv6-after-bracket"),
    pytest.param("call 801 555 1AKIAIOSFODNN7EXAMPLE", "IOSFODNN7EXAMPLE", id="key-after-number"),
    pytest.param("1.1.1.1AKIAIOSFODNN7EXAMPLE", "IOSFODNN7EXAMPLE", id="key-after-ip"),
    # the code rule with brackets, quotes, commas and no separator
    pytest.param("code (4821)", "4821", id="code-parens"),
    pytest.param("code, 4821", "4821", id="code-comma"),
    pytest.param('code "4821"', "4821", id="code-quotes"),
    pytest.param("OTP4821", "4821", id="otp-glued"),
    pytest.param("PIN1234", "1234", id="pin-glued"),
    # normalisation exposes digits and schemes
    pytest.param("call ８０１５５５１２３４", "1234", id="fullwidth-digits"),
    pytest.param("see ｈｔｔｐｓ://example.com/a now", "example.com", id="fullwidth-scheme"),
]


@pytest.mark.parametrize(("text", "leaked"), _LEAKS)
def test_redact_masks_what_the_review_found_unmasked(text: str, leaked: str) -> None:
    assert leaked not in redact(text)


@pytest.mark.parametrize("text", [row.values[0] for row in _LEAKS])
def test_redact_is_idempotent_on_every_gap_case(text: str) -> None:
    once = redact(text)

    assert redact(once) == once


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Your code: 48213", "Your code: [number]"),
        ("Your PIN is 1234.", "Your PIN is [number]."),
        ("reset at example.com/reset?token=abcdef now", "reset at [url] now"),
        ("see www.x.com now", "see [url] now"),
        ("key AKIAIOSFODNN7EXAMPLE end", "key [token] end"),
        ("key ghp_" + _LETTERS[:36] + " end", "key [token] end"),
        ("key sk-" + _LETTERS[:30] + ".", "key [token]."),
        ("tok " + "a" * 32 + " end", "tok [token] end"),
        ("auth " + ".".join(_JWT_PARTS) + " ok", "auth [token] ok"),
        (".".join(_JWT_PARTS), "[token]"),
        ("abc/" + "x" * 32 + "/def", "[token]"),
        ("call 415/555/0132 now", "call [number] now"),
        ("call 415–555–0132 now", "call [number] now"),
        ("call 4_1_5_5_5_5_0_1_3_2 now", "call [number] now"),
        ("ref 12345,67890 ok", "ref [number] ok"),
        ("host 10.0.0.1 down", "host [ip] down"),
        ("dns 8.8.8.8.", "dns [ip]."),
        ("addr fe80::1 up", "addr [ip] up"),
        ("addr 2001:0db8:85a3:0000:0000:8a2e:0370:7334 up", "addr [ip] up"),
        ("addr [::1]:8080 up", "addr [[ip]]:8080 up"),
        ("mail bob＠example.com now", "mail [email] now"),
        ("mail bob [at] example [dot] com now", "mail [email] now"),
        ("mail bob(at)example(dot)com now", "mail [email] now"),
        ("Reset link:example.com/reset?token=abcdef now", "Reset link:[url] now"),
        ("addr fe80::1: refused", "addr [ip]: refused"),
        ("IPv6:2001:db8::1", "IPv6:[ip]"),
        ("call 801\u200b555\u200b1234 now", "call [number] now"),
        ("code (4821)", "code ([number])"),
        ("OTP4821", "OTP[number]"),
        ("[EXTERNAL]www.bank.com/reset?t=ab12cd", "[EXTERNAL][url]"),
        ("[eth0]fe80::1", "[eth0][ip]"),
        ("call 801 555 1AKIAIOSFODNN7EXAMPLE", "call [number][token]"),
        ("1.1.1.1AKIAIOSFODNN7EXAMPLE", "[ip][token]"),
        ("x 80 1.000000000000000000000000 y", "x [number] y"),
        ("x 1 2 000000000000000000000000= y", "x [number]= y"),
        ("x 0 0 0 0-00-000-000-000-000-000 y", "x [number] y"),
        ("a::000000", "a::[number]"),
        ("10.0.0.1a::", "[ip]a::"),
        ("02026-11-09www.code ", "[number]www.code "),
        ("[number]example.com/x", "[number]example.com/x"),
        ("x 0 0 0.0.0.0 y", "x [number] y"),
        ("x 0 0.0.0.0 y", "x 0 [ip] y"),
        ("x 10.0.0.1 y", "x [ip] y"),
        ("x 192.168.1.1 y", "x [ip] y"),
        ("x 1.1.1.1 2 y", "x [ip] 2 y"),
        ("x 2026-11-09 1.2.3.4 y", "x 2026-11-09 [ip] y"),
        ("x ::ffff:10.0.0.1 y", "x [ip] y"),
        ("backup codes 48213 and 99107", "backup codes [number] and [number]"),
        ("peer fe80::1.Then retry", "peer [ip].Then retry"),
        ("call " + "\u0332".join("8015551234") + " now", "call [number] now"),
    ],
)
def test_redact_uses_the_documented_marker(text: str, expected: str) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ｈｅｌｌｏ", "hello"),
        ("ﬁle", "file"),
        ("① ½", "1 1⁄2"),
        ("a b", "a b"),
    ],
)
def test_redact_returns_the_nfkc_normalised_text(text: str, expected: str) -> None:
    assert redact(text) == expected
    assert redact(text) == unicodedata.normalize("NFKC", text)


@given(st.text())
def test_redact_output_is_always_nfkc_normalised(text: str) -> None:
    result = redact(text)

    assert unicodedata.normalize("NFKC", result) == result


_PARAGRAPH = (
    "Hi team. This week's internationalization workshop moves to Room 12 on Tuesday. "
    "Please read antidisestablishmentarianism and the electroencephalographically "
    "annotated notes before class. The pin goes on the board, the code stays in the repo, and the "
    "verification step is optional. See src/command_center/core/redact.py or "
    "docs/contracts/core.md for the rule list; the tests under tests/ cover it. "
    "Quiz 3 covers Chapter 12 (pages 40-55). "
    "Lunch costs $19.99 or $1,299.00 for the whole club. Bring a charger, a notebook, and a pen."
)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("due 2026-11-09", id="iso-date"),
        pytest.param("code due 2026-11-09", id="iso-date-after-code"),
        pytest.param("pin the sign on 2026-11-09", id="iso-date-after-pin-word"),
        pytest.param("2026-11-09\u20132026-11-12", id="iso-range-en-dash"),
        pytest.param("2026-11-09\u20142026-11-12", id="iso-range-em-dash"),
        pytest.param("2026-11-09/2026-11-12", id="iso-range-slash"),
        pytest.param("2026-11-09 \u2013 2026-11-12", id="iso-range-spaced"),
        pytest.param("2026-11-09 to 2026-11-12", id="iso-range-words"),
        pytest.param("code due 2026-11-09\u20132026-11-12", id="iso-range-after-code"),
        pytest.param("Cafe::new and Base::new and Class::method", id="perl-style-paths"),
        pytest.param("note: see the Facade", id="hex-letters-before-colon"),
        pytest.param("at 10:30", id="time"),
        pytest.param("at 10:30:45", id="time-seconds"),
        pytest.param("10:30-11:45", id="time-range"),
        pytest.param("costs $19.99", id="price"),
        pytest.param("costs $1,299.00", id="price-thousands"),
        pytest.param("a pop of 1,234,567", id="thousands-count"),
        pytest.param("Python 3.12.1", id="version"),
        pytest.param("release v3.12.1 is out", id="version-prefixed"),
        pytest.param("the code", id="bare-code"),
        pytest.param("code", id="code-alone"),
        pytest.param("Code review", id="code-review"),
        pytest.param("Please review the code before Friday", id="code-sentence"),
        pytest.param("pin and verification and passcode and otp", id="keywords-without-digits"),
        pytest.param("code 12", id="code-short-number"),
        pytest.param("pincode and zipcode words", id="compound-words"),
        pytest.param("the barcode 1234 stays", id="barcode-is-not-code"),
        pytest.param("room 12345 ok", id="five-digit-room"),
        pytest.param("CS 101 midterm", id="course"),
        pytest.param("see std::vector and Foo::bar", id="namespace-paths"),
        pytest.param("e.g. this, i.e. that", id="abbreviations"),
        pytest.param("and/or either/or I/O", id="slash-words"),
        pytest.param("src/command_center/core/redact.py", id="repo-path"),
        pytest.param("the report.pdf and notes.txt files", id="filenames"),
        pytest.param("internationalization", id="long-word-20"),
        pytest.param("antidisestablishmentarianism", id="long-word-28"),
        pytest.param("a" * 31, id="letters-31"),
        pytest.param("a" * 22 + "1", id="digit-run-23"),
        pytest.param(_PARAGRAPH, id="ordinary-paragraph"),
    ],
)
def test_redact_leaves_ordinary_text_alone(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("code 2026-11-09 and 4821", "code 2026-11-09 and 4821", id="date-then-number"),
        pytest.param("Code: 12345 6", "Code: [number]", id="five-digits-then-digit"),
        pytest.param("PIN 1234.5", "PIN 1234.5", id="decimal-after-pin"),
        pytest.param(
            "pin one two three four five six 4821",
            "pin one two three four five six 4821",
            id="six-words-away",
        ),
        pytest.param(
            "pin one two three four five 4821",
            "pin one two three four five [number]",
            id="five-words-away",
        ),
        pytest.param("barcode 4821 pin", "barcode [number] pin", id="digits-before-keyword"),
    ],
)
def test_redact_code_rule_window_and_edges(text: str, expected: str) -> None:
    assert redact(text) == expected


_LONG = 200_000
_TIME_BUDGET_SECONDS = 0.5


def _long(unit: str) -> str:
    return (unit * (_LONG // len(unit) + 1))[:_LONG]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(_long("a"), id="letters"),
        pytest.param(_long("a."), id="dot-joined"),
        pytest.param(_long("a/"), id="slash-joined"),
        pytest.param(_long("a1/"), id="digit-slash"),
        pytest.param(_long("a" * 31 + "."), id="dots-after-31-letters"),
        pytest.param(_long("a" * 23 + "1."), id="dots-after-24-run"),
        pytest.param(_long("eyJ" + "a" * 20 + "."), id="jwt-prefix-repeated"),
        pytest.param("eyJ" + "a" * (_LONG - 3), id="jwt-prefix-long"),
        pytest.param(_long("AKIA"), id="akia-repeated"),
        pytest.param(_long("ghp_"), id="ghp-repeated"),
        pytest.param(_long("sk-"), id="sk-repeated"),
        pytest.param(_long("xoxb-"), id="xox-repeated"),
        pytest.param(_long("AIza"), id="aiza-repeated"),
        pytest.param(_long("a+"), id="plus"),
        pytest.param(_long("a="), id="equals"),
        pytest.param("a" * 31 + "=" * (_LONG - 31), id="equals-tail"),
        pytest.param(_long("1/"), id="digit-slash-pairs"),
        pytest.param(_long("1_"), id="digit-underscore"),
        pytest.param(_long("1–"), id="digit-en-dash"),
        pytest.param(_long("1—"), id="digit-em-dash"),
        pytest.param(_long("1 "), id="digit-no-break-space"),
        pytest.param(_long("1,"), id="digit-comma"),
        pytest.param(_long("1234,"), id="four-digits-comma"),
        pytest.param(_long("12345,"), id="five-digits-comma"),
        pytest.param(_long("1."), id="digit-dot"),
        pytest.param(_long("1.1.1."), id="ipv4-like"),
        pytest.param(_long("255.255.255.255."), id="ipv4-like-long"),
        pytest.param(_long("1.1.1.1 "), id="ipv4-spaced"),
        pytest.param(_long(":"), id="colons"),
        pytest.param(_long("a:"), id="hex-colon"),
        pytest.param(_long("a: "), id="hex-colon-space"),
        pytest.param(_long("::"), id="double-colons"),
        pytest.param(_long("a::"), id="hex-double-colon"),
        pytest.param(_long("f:" * 7 + "f "), id="seven-colon-groups"),
        pytest.param(_long("fe80::1 "), id="ipv6-spaced"),
        pytest.param(_long("1:2:3:4:5:6:7:8 "), id="ipv6-full-spaced"),
        pytest.param(_long("a" * 45 + ":"), id="long-hex-run"),
        pytest.param(_long("www."), id="www-repeated"),
        pytest.param(_long("www.a."), id="www-labels"),
        pytest.param(_long("a.b."), id="host-labels"),
        pytest.param(_long("a-"), id="host-hyphens"),
        pytest.param(_long("a.b/"), id="host-with-path-repeated"),
        pytest.param(_long("a.bc/ "), id="host-with-path-spaced"),
        pytest.param("a." * 1000 + "x" * (_LONG - 2000), id="labels-then-long-tld"),
        pytest.param(_long("a" * 62 + "."), id="max-length-labels"),
        pytest.param(_long("code "), id="code-repeated"),
        pytest.param(_long("code a "), id="code-words"),
        pytest.param("code " + "a " * (_LONG // 2), id="code-then-words"),
        pytest.param("code " + "a" * _LONG, id="code-then-long-word"),
        pytest.param(_long("code: "), id="code-colons"),
        pytest.param(_long("pin 1234 "), id="pin-with-digits"),
        pytest.param(_long("pin 12345"), id="pin-glued-digits"),
        pytest.param(_long("passcode "), id="passcode-repeated"),
        pytest.param(_long("otp "), id="otp-repeated"),
        pytest.param(_long("verification "), id="verification-repeated"),
        pytest.param(_long("[at]"), id="at-brackets"),
        pytest.param(_long("a[at]"), id="at-brackets-prefixed"),
        pytest.param(_long("a [at] "), id="at-brackets-spaced"),
        pytest.param(_long("a(at)b(dot)"), id="at-dot-parens"),
        pytest.param("a[at]" + "b" * (_LONG - 5), id="at-then-long-domain"),
        pytest.param("a[at]b" + "[dot]c" * (_LONG // 6), id="at-then-many-dots"),
        pytest.param(_long("[dot]"), id="dot-brackets"),
        pytest.param(_long("@"), id="at-signs"),
        pytest.param(_long("a@"), id="at-after-letters"),
        pytest.param(_long("\ufb03"), id="nfkc-expanding-ligature"),
        pytest.param("a" + "\u0316\u0301" * (_LONG // 2), id="nfkc-combining-marks-misordered"),
        pytest.param(_long("\u200b"), id="zero-width-spaces"),
        pytest.param(_long("1\u200b"), id="digit-zero-width-space"),
        pytest.param(_long("-"), id="hyphens-again"),
        pytest.param("--" + "a." * (_LONG // 2), id="hyphen-prefixed-labels"),
        pytest.param("code" + "(" * _LONG, id="code-then-brackets"),
        pytest.param(_long("code,"), id="code-commas"),
        pytest.param("code " + "1111 " * (_LONG // 5), id="code-then-many-codes"),
        pytest.param(_long("code 1111 and "), id="code-repeated-with-codes"),
        pytest.param("a\u0332" * (_LONG // 2) + "1", id="underlined-letters"),
        pytest.param(_long("1\u0332"), id="underlined-digits"),
        pytest.param(_long("code("), id="code-open-parens"),
        pytest.param(_long("addr:fe80::1: "), id="ipv6-colon-spaced"),
        pytest.param(_long(":"), id="colons-again"),
        pytest.param(_long("Ab1/"), id="base64-like-slashes"),
        pytest.param(_long("2026-11-09\u2013"), id="iso-range-chain"),
        pytest.param(_long("2026-11-09/"), id="iso-slash-chain"),
        pytest.param(_long("Ａ"), id="fullwidth-letters"),
        pytest.param(_long("１．"), id="fullwidth-digit-dot"),
        pytest.param(_long("https://a.b/"), id="scheme-url-repeated"),
        pytest.param(_long("https://"), id="scheme-only"),
        pytest.param(_long("[token][url][ip][email][number]"), id="markers"),
        pytest.param(_long("-"), id="hyphens"),
        pytest.param(_long("_"), id="underscores"),
        pytest.param(_long("(1"), id="open-paren-digit"),
        pytest.param(_long("2026-11-09 "), id="iso-dates"),
    ],
)
def test_redact_finishes_quickly_on_adversarial_input_of_200k_characters(text: str) -> None:
    assert len(text) >= _LONG
    started = time.perf_counter()
    redact(text)

    assert time.perf_counter() - started < _TIME_BUDGET_SECONDS


_GAP_ALPHABET = st.sampled_from(
    [
        *"ab1fFAKIAeyJ.,:/_+=-()[] – ＠@xwdotcodepin0123456789",
        *["code ", "pin ", "otp ", "[at]", "(dot)", "www.", "::"],
        *["ghp_", "sk-", "10.0.0.1", "eyJ"],
        *[
            "\u200b",
            "\u00ad",
            "\ufe0f",
            "\u0332",
            "codes ",
            "\u2014",
            "2026-11-09",
            "(",
            ")",
            '"',
            ",",
        ],
    ]
)


@given(st.lists(_GAP_ALPHABET, max_size=40).map("".join))
def test_redact_is_idempotent_on_text_built_from_the_new_rules_pieces(text: str) -> None:
    once = redact(text)

    assert redact(once) == once


@given(
    st.text(alphabet="abcdefghij ", max_size=10),
    st.integers(min_value=1000, max_value=99999),
)
def test_redact_never_leaks_a_code_after_a_keyword(prefix: str, code: int) -> None:
    result = redact(f"{prefix} verification code: {code} thanks")

    assert str(code) not in result
