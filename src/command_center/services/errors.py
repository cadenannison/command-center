"""Failure classes the services raise for their callers (the api maps them to responses)."""

from command_center.core.redact import redact, trim


class UnknownSourceError(Exception):
    """The named source has no adapter registered."""

    def __init__(self, source: str) -> None:
        super().__init__(f"Unknown source {source!r}: no adapter is registered under that name")
        self.source = source


class CredentialRejectedError(Exception):
    """A pairing token or refresh credential was not accepted.

    One message for every cause (unknown, expired, used, reused): the caller learns nothing it
    could use to tell them apart. The cause goes to the log as a reason code.
    """

    def __init__(self) -> None:
        super().__init__("The pairing token or credential is not valid")


class PairingLockedError(Exception):
    """Too many recent failures; nothing is checked until the lock ends."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Too many failed attempts; try again in {retry_after_seconds} seconds")
        self.retry_after_seconds = retry_after_seconds


class GeocodeRateLimitedError(Exception):
    """Too many city searches in the last minute; nothing was sent to the provider."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Too many city searches; try again in {retry_after_seconds} seconds")
        self.retry_after_seconds = retry_after_seconds


class GeocodeUnavailableError(Exception):
    """The city search provider failed. The message is redacted and never holds the query."""


class SummaryUnavailableError(Exception):
    """The summary provider could not produce a summary.

    `reason` is `rate_limited` or `failed`. The message carries the reason only, never the
    provider's own text, so it is safe to show.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"The summary provider is unavailable: {reason}")
        self.reason = reason


class UnknownSummaryProviderError(ValueError):
    """The named summary provider is not one of the supported ones."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"Unknown summary provider {provider!r}: choose gemini or ollama")
        self.provider = provider


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
