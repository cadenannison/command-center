"""Redaction for AI-summary input. Runs before any provider sees data; never carries bodies."""

import re

# The scheme plus everything up to whitespace: one forward scan, no backtracking.
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
# A maximal run of 24+ token characters. The lookbehind pins the start to the run's first
# character (unanchored, every start inside a long run would rescan it: quadratic); the greedy body
# then takes the whole run, so the run is maximal and each character is read once. Whether it holds
# a digit is checked in the callback, so a long digit-free word is a single O(n) scan.
_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{24,}")
_ASCII_DIGIT = re.compile(r"[0-9]")
# Anchored at a token start: unanchored, every start inside a long token rescans it (quadratic).
_EMAIL = re.compile(r"(?<!\S)\S+@\S+")
# A run of digits joined by whitespace, dashes, dots or parentheses, with an optional opening "(".
_DIGIT_GROUP = re.compile(r"\(?\d(?:[\s().\-]*\d)*")
# An ISO date (ASCII digits, real month and day) with nothing attached: it must sit between
# whitespace or the edges of its digit group, so 2026-11-07-1234 or 2026-11-07.5 do not count.
_ISO_DATE = re.compile(r"(?<!\S)[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])(?!\S)")
_MIN_DIGITS = 6
_ELLIPSIS = "…"


def redact(text: str) -> str:
    """Replace URLs, token-like runs, emails and digit groups of 6+ digits with markers.

    Markers are [url], [token], [email] and [number]. URLs go first because they may hold an "@",
    digits and query tokens. Emails go before tokens: an email is a whole whitespace-delimited
    token, so masking it first removes any token inside it in one step, and no marker is left
    glued to a half-masked address. The digit rule runs last, after tokens already swallowed their
    digits.

    Over-redaction is deliberate: a false positive costs a word of context, a miss leaks data.
    Run it before trim, never after, so a cut cannot leave a partial number behind.
    """
    without_urls = _URL.sub("[url]", text)
    without_emails = _EMAIL.sub("[email]", without_urls)
    without_tokens = _TOKEN.sub(_redact_token, without_emails)
    return _DIGIT_GROUP.sub(_redact_group, without_tokens)


def _redact_token(match: re.Match[str]) -> str:
    run = match.group()
    return "[token]" if _ASCII_DIGIT.search(run) else run


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
    return f"{lead}[number]{trail}"


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
