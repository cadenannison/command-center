"""Redaction for AI-summary input. Runs before any provider sees data; never carries bodies.

Best-effort defence in depth, not a guarantee (decision 0240): it masks the shapes below and will
miss a secret written in a shape nobody listed. The caller still decides what text goes in.
"""

import ipaddress
import re
import unicodedata

# The scheme plus everything up to whitespace: one forward scan, no backtracking.
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
# A scheme-less URL: "www." plus a host, or a dotted host with an alphabetic TLD followed by a path,
# query or fragment. The lookbehind pins the start to the first character of a run, so an
# unmatched run is scanned once ("-*" lets "--example.com" match; ":" before it is allowed, so
# "URL:example.com/x" does too; not right after a marker, so "[number]www.x.com" is stable, decision
# 0261);
# labels are at most 63 characters, so none backtracks far.
# The markers redact writes. A rule that must not start right after one (a second pass would then
# match what the first pass could not) puts _NOT_AFTER_MARKER in its lookbehind: one fixed-width
# negative lookbehind per marker, so a user's own "]" ("[EXTERNAL]www.x.com") does not block it.
_MARKERS = ("[url]", "[email]", "[token]", "[ip]", "[number]")
_NOT_AFTER_MARKER = "".join(rf"(?<!{re.escape(marker)})" for marker in _MARKERS)
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_TLD = r"[a-z]{2,24}"
# Never starts right after one of our markers (decision 0261), so a second pass finds nothing new.
_BARE_URL = re.compile(
    rf"{_NOT_AFTER_MARKER}(?<![\w@./-])-*(?:www\.(?:{_LABEL}\.)*{_TLD}(?::\d{{1,5}})?(?:[/?#]\S*)?"
    rf"|(?:{_LABEL}\.)+{_TLD}(?::\d{{1,5}})?[/?#]\S*)",
    re.IGNORECASE,
)
# Anchored at a token start: unanchored, every start inside a long token rescans it (quadratic).
_EMAIL = re.compile(r"(?<!\S)\S+@\S+")
# "bob [at] example [dot] com", "bob(at)example(dot)com": a local part, an "at" spelled in brackets
# or parentheses, then a domain whose dots may be spelled the same way.
_AT = r"[ \t]?[\[(][ \t]?at[ \t]?[\])][ \t]?"
_DOT = r"[ \t]?(?:[\[(][ \t]?dot[ \t]?[\])]|\.)[ \t]?"
_SPELLED_EMAIL = re.compile(rf"(?<!\S)[^\s@]+{_AT}[a-z0-9-]+(?:{_DOT}[a-z0-9-]+)+", re.IGNORECASE)
# Known provider key shapes. The lookbehind pins the start; the tail takes the rest of the key.
_KEY = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"AKIA[A-Z0-9]{16}"
    r"|gh[pous]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{16,}"
    r"|sk-[A-Za-z0-9_-]{16,}"
    r"|xox[baprs]-[A-Za-z0-9-]{8,}"
    r"|AIza[A-Za-z0-9_-]{20,}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}(?:\.[A-Za-z0-9_-]*)?"
    r")[A-Za-z0-9_-]*"
)
# A maximal run of 24+ characters from the token alphabet, "." and "/" included so a token split by
# them is one run. The lookbehind pins the start to the run's first character (unanchored, every
# start inside a long run would rescan it: quadratic). What the run holds is judged in the callback.
_RUN = re.compile(r"(?<![A-Za-z0-9_+/=.-])[A-Za-z0-9_+/=.-]{24,}")
# The parts of a run between "." and "/" (the same pinned-start pattern, so linear).
_PART = re.compile(r"(?<![A-Za-z0-9_+=-])[A-Za-z0-9_+=-]{24,}")
_ASCII_DIGIT = re.compile(r"[0-9]")
_ASCII_ALNUM = re.compile(r"[A-Za-z0-9]")
_DIGITS_AND_SEPARATORS = re.compile(r"[0-9_./+=-]+")
_ASCII_UPPER = re.compile(r"[A-Z]")
_ASCII_LOWER = re.compile(r"[a-z]")
_PART_ANY = 32
_RUN_BASE64 = 32
_IPV4_OCTET = r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])"
_IPV4_FULL = re.compile(rf"{_IPV4_OCTET}(?:\.{_IPV4_OCTET}){{3}}")
_IPV4 = re.compile(rf"(?<![0-9.]){_IPV4_OCTET}(?:\.{_IPV4_OCTET}){{3}}(?![0-9]|\.[0-9])")
# A maximal run of hex digits, ":" and "." (an IPv6 address, possibly with a dotted IPv4 tail).
# Whether it is an address is decided by ipaddress in the callback. Never starts right after one of
# our markers (decision 0261), so a second pass finds nothing new.
_IPV6_RUN = re.compile(rf"{_NOT_AFTER_MARKER}(?<![0-9A-Za-z.])[0-9A-Fa-f:.]{{2,}}")
_IPV6_MAX_LENGTH = 45
_IPV6_MIN_COLONS = 2
_HEX_DIGIT = re.compile(r"[0-9A-Fa-f]")
# A run of digits joined by whitespace (no-break spaces included), dashes (en and em dashes too),
# dots, "/", "_", parentheses or combining marks (an underlined or struck-through digit), with an
# optional opening "(". A comma joins two runs only when
# both sides of it have 4+ digits ("12345,67890"), so "$1,299.00" and "1,234,567" are not joined.
_SEPARATORS = r"[\s().\-/_\u2010-\u2015\u2212\u0300-\u036f]"
_DIGIT_GROUP = re.compile(rf"\(?\d(?:(?:{_SEPARATORS}+|(?<=\d{{4}}),(?=\d{{4}}))?\d)*")
# An ISO date (ASCII digits, real month and day), or a range of them joined by an en dash, an em
# dash or "/", with nothing attached: it must sit between whitespace or the edges of its digit
# group, so 2026-11-07-1234 or 2026-11-07.5 do not count.
_ISO_DAY = r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
_ISO_DATE = re.compile(rf"(?<!\S){_ISO_DAY}(?:[\u2013\u2014/]{_ISO_DAY})*(?!\S)")
_MIN_DIGITS = 6
# A 4-5 digit run after code, otp, pin, passcode or verification, with at most five words and any
# of ":", "#", "=", "-", brackets, quotes (straight and curly), commas, dashes, "*", ";", "&" or
# whitespace between (or nothing: "OTP4821").
# Not part of a longer number, date or decimal.
_CODE_GAP = r"[\s:#=(),\"'\[\]*;&|>\u00ab\u00bb\u2010-\u2015\u2018-\u201f\u2192\u2212-]"
_CODE_DIGITS = r"\d{4,5}(?!\d|[-/.]\d)"
_CODE_WORDS = rf"(?:{_CODE_GAP}+[A-Za-z]+){{0,5}}?"
# The first code, then every further code within five words of the previous one ("codes 48213 and
# 99107"): one match covers them all, so the result needs no second pass to be stable.
_CODE = re.compile(
    r"(?<![A-Za-z])(?:code|otp|pin|passcode|verification)s?(?![A-Za-z])"
    rf"{_CODE_WORDS}{_CODE_GAP}*{_CODE_DIGITS}(?:{_CODE_WORDS}{_CODE_GAP}+{_CODE_DIGITS})*",
    re.IGNORECASE,
)
_DIGIT_RUN = re.compile(r"\d+")
# Characters that render as nothing (the Unicode Default_Ignorable_Code_Point set: soft hyphen,
# grapheme joiner, Hangul and Khmer fillers, Mongolian and variation selectors, zero-width and bidi
# marks, word joiners, BOM, tag characters): removed first, or "801<ZWSP>555<ZWSP>1234" would hide a
# number from every rule.
_INVISIBLE = re.compile(
    "[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e"
    "\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufff8\U0001bca0-\U0001bca3"
    "\U0001d173-\U0001d17a\U000e0000-\U000e0fff]"
)
_ELLIPSIS = "…"


def redact(text: str) -> str:
    """Replace URLs, emails, keys and tokens, IP addresses, codes and digit groups with markers.

    The text is NFKC-normalised first (fullwidth at signs and digits, no-break spaces,
    compatibility forms), and the RESULT is the normalised text: that is what goes onward, never
    the original spelling (decision 0240). Markers are [url], [email], [token], [ip] and [number].

    Rules, in order: scheme URLs; scheme-less URLs; emails; spelled-out emails ("[at]", "(dot)");
    known key prefixes and JWTs; token runs (24+ characters with a digit, or 32+ without one, also
    when joined by "." or "/"); IPv6; digit groups of 6+ digits; IPv4 (after the digit groups,
    decision 0255); a 4-5 digit code after code, otp, pin, passcode or verification. URLs go
    first because they may hold an "@", digits and query tokens. Emails go before tokens: an email
    is a whole whitespace-delimited token, so masking it first leaves no marker glued to a
    half-masked address. The digit rules run last, after tokens already swallowed their digits.

    Over-redaction is deliberate: a false positive costs a word of context, a miss leaks data.
    Run it before trim, never after, so a cut cannot leave a partial number behind.
    """
    normalised = unicodedata.normalize("NFKC", _INVISIBLE.sub("", text))
    without_urls = _BARE_URL.sub("[url]", _URL.sub("[url]", normalised))
    without_emails = _SPELLED_EMAIL.sub("[email]", _EMAIL.sub("[email]", without_urls))
    without_keys = _KEY.sub("[token]", without_emails)
    without_tokens = _RUN.sub(_redact_run, without_keys)
    without_ipv6 = _IPV6_RUN.sub(_redact_ipv6, without_tokens)
    # IPv4 runs after the digit rule, so it never claims part of a run that rule masks whole
    # (decision 0255): "0 0 0.0.0.0" is one number, "1.1.1.1 2" is an address and a digit.
    without_numbers = _DIGIT_GROUP.sub(_redact_group, without_ipv6)
    without_ips = _IPV4.sub("[ip]", without_numbers)
    # A key glued after digits is blocked by the digit until the digit rule turns it into a marker.
    return _CODE.sub(_redact_code, _KEY.sub("[token]", without_ips))


def _redact_run(match: re.Match[str]) -> str:
    run = match.group()
    core = run.rstrip(".")
    # Digits and separators only: the digit rule masks the whole group, neighbours included, so a
    # token mark here would leave the digits next to it showing ("0 0 0 0-00-000-000-000-000-000";
    # decision 0261).
    if _is_token_run(core) and _DIGITS_AND_SEPARATORS.fullmatch(core) is None:
        return "[token]" + run[len(core) :]
    return run


def _is_token_run(core: str) -> bool:
    for part in _PART.finditer(core):
        value = part.group()
        if _ASCII_DIGIT.search(value):
            return True
        if len(value) >= _PART_ANY and _ASCII_ALNUM.search(value):
            return True
    # Base64 carries "+", "/" and "=" and no ".": the "/" splits it into short parts, so measure the
    # whole run: 32+ with a "+" or "=", or with a digit and both letter cases (a secret key like
    # wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY).
    if len(core) < _RUN_BASE64 or "." in core or _ASCII_ALNUM.search(core) is None:
        return False
    if "+" in core or "=" in core:
        return True
    return (
        _ASCII_DIGIT.search(core) is not None
        and _ASCII_UPPER.search(core) is not None
        and _ASCII_LOWER.search(core) is not None
    )


def _redact_ipv6(match: re.Match[str]) -> str:
    run = match.group()
    # A run followed by a letter or digit is part of a word ("Cafe::new"), not an address; a run
    # that ends in "." is a sentence end, so the letter after it starts the next word. A "[" after
    # it is a marker we put there ("a::[number]"), so the run was a word, not an address.
    after = match.string[match.end() : match.end() + 1]
    glued = match.string.startswith(_MARKERS, match.end())
    if not run.endswith(".") and (after.isalnum() or glued):
        return run
    lead = 1 if run.startswith(":") and not run.startswith("::") else 0
    for start in dict.fromkeys((0, lead)):
        body = run[start:]
        for candidate in dict.fromkeys((body, body.rstrip(".:"))):
            if _is_ipv6(candidate):
                return run[:start] + "[ip]" + run[start + len(candidate) :]
    return run


def _is_ipv6(candidate: str) -> bool:
    if len(candidate) > _IPV6_MAX_LENGTH or candidate.count(":") < _IPV6_MIN_COLONS:
        return False
    if _HEX_DIGIT.search(candidate) is None:
        return False
    try:
        ipaddress.IPv6Address(candidate)
    except ValueError:
        return False
    return True


def _redact_code(match: re.Match[str]) -> str:
    return _DIGIT_RUN.sub("[number]", match.group())


def _redact_group(match: re.Match[str]) -> str:
    group = match.group()
    opener, body = (group[0], group[1:]) if group.startswith("(") else ("", group)
    redacted = _redact_body(body)
    # An opening "(" is dropped only when it belonged to a bracketed number we replaced.
    if opener and (redacted == body or ")" not in body):
        return opener + redacted
    return redacted


def _redact_body(body: str) -> str:
    parts: list[str] = []
    position = 0
    for date in _ISO_DATE.finditer(body):
        parts.append(_redact_digits(body[position : date.start()]))
        parts.append(date.group())
        position = date.end()
    parts.append(_redact_digits(body[position:]))
    return "".join(parts)


def _redact_digits(piece: str) -> str:
    if sum(char.isdigit() for char in piece) < _MIN_DIGITS:
        return piece
    lead = piece[: len(piece) - len(piece.lstrip())]
    trail = piece[len(piece.rstrip()) :]
    marker = "[ip]" if _IPV4_FULL.fullmatch(piece.strip()) else "[number]"
    return f"{lead}{marker}{trail}"


def trim(text: str, limit: int) -> str:
    """Strip text and cap it at limit characters, ending in an ellipsis when cut."""
    if limit < 0:
        msg = f"trim limit must be >= 0, got {limit}"
        raise ValueError(msg)
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    if limit == 0:
        return ""
    return stripped[: limit - 1].rstrip() + _ELLIPSIS
