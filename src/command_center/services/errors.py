"""Failure classes the services raise for their callers (the api maps them to responses)."""

from command_center.core.redact import redact, trim


class UnknownSourceError(Exception):
    """The named source has no adapter registered."""

    def __init__(self, source: str) -> None:
        super().__init__(f"Unknown source {source!r}: no adapter is registered under that name")
        self.source = source


_MESSAGE_LIMIT = 200


def error_text(exc: Exception) -> str:
    """The full text of an exception: its message, else its class name. Not bounded or redacted."""
    return str(exc) or type(exc).__name__


def describe(exc: Exception) -> str:
    """Short, bounded text for an exception, for log lines. Messages for display use error_text."""
    return error_text(exc)[:_MESSAGE_LIMIT]


def safe_message(message: str) -> str:
    """Redact, then trim to 200 characters: trimming first could cut a number in half.

    Every message a service keeps or returns for display goes through it (decision 0052).
    """
    return trim(redact(message), _MESSAGE_LIMIT)
