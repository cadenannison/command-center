"""Failure classes for source adapters. Adapters translate vendor errors into these."""


class SourceError(Exception):
    """Base for every failure a source adapter reports."""


class AuthExpired(SourceError):  # noqa: N818  (name fixed by the task card)
    """Credentials were rejected or have expired; the user must reconnect."""


class TransientError(SourceError):
    """Temporary failure (timeout, rate limit, 5xx); a later retry may succeed."""


class FatalError(SourceError):
    """Permanent failure (malformed data, unsupported request); retrying will not help."""


class SecretStoreError(Exception):
    """The secret store (OS keychain) cannot be used. The message says why, never a secret value."""


class SummaryProviderError(Exception):
    """A summary provider failed (unreachable, bad key, malformed output).

    The message never carries a secret or the prompt.
    """


class SummaryRateLimited(SummaryProviderError):  # noqa: N818  (name fixed by the task card)
    """The summary provider rejected the call for rate or quota reasons; retry later."""


class ChatProviderError(Exception):
    """A chat provider failed (unreachable, bad key, malformed output).

    The message never carries a secret, the key or the prompt.
    """


class ChatRateLimited(ChatProviderError):  # noqa: N818  (name fixed by the task card)
    """The chat provider rejected the call for rate or quota reasons; retry later."""
