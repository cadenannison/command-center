"""Failure classes for source adapters. Adapters translate vendor errors into these."""


class SourceError(Exception):
    """Base for every failure a source adapter reports."""


class AuthExpired(SourceError):  # noqa: N818  (name fixed by the task card)
    """Credentials were rejected or have expired; the user must reconnect."""


class TransientError(SourceError):
    """Temporary failure (timeout, rate limit, 5xx); a later retry may succeed."""


class FatalError(SourceError):
    """Permanent failure (malformed data, unsupported request); retrying will not help."""
