"""Redaction for AI-summary input. Runs before any provider sees data; never carries bodies."""

import re

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
    """Replace email addresses and digit groups of 6+ digits with [email] / [number].

    Over-redaction is deliberate: a false positive costs a word of context, a miss leaks data.
    Run it before trim, never after, so a cut cannot leave a partial number behind.
    """
    return _DIGIT_GROUP.sub(_redact_group, _EMAIL.sub("[email]", text))


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
