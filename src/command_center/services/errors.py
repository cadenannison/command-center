"""Failure classes the services raise for their callers (the api maps them to responses)."""


class UnknownSourceError(Exception):
    """The named source has no adapter registered."""

    def __init__(self, source: str) -> None:
        super().__init__(f"Unknown source {source!r}: no adapter is registered under that name")
        self.source = source


_MESSAGE_LIMIT = 200


def describe(exc: Exception) -> str:
    """Short, bounded text for an exception: its message, else its class name."""
    return (str(exc) or type(exc).__name__)[:_MESSAGE_LIMIT]
