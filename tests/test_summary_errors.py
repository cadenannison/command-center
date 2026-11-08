"""Summary provider errors: their own family, separate from source failures."""

import pytest

from command_center.core.errors import SourceError, SummaryProviderError, SummaryRateLimited

MESSAGE = "Failed to summarise with gemini: provider unreachable"


def test_rate_limited_is_a_summary_provider_error() -> None:
    assert issubclass(SummaryRateLimited, SummaryProviderError)


def test_summary_errors_are_not_source_errors() -> None:
    assert not issubclass(SummaryProviderError, SourceError)
    assert not issubclass(SummaryRateLimited, SourceError)


def test_summary_provider_error_is_not_a_rate_limit() -> None:
    assert not issubclass(SummaryProviderError, SummaryRateLimited)


def test_summary_provider_error_carries_its_message() -> None:
    with pytest.raises(SummaryProviderError, match="unreachable"):
        raise SummaryProviderError(MESSAGE)


def test_rate_limit_is_caught_as_a_provider_error() -> None:
    msg = "Failed to summarise with gemini: rate limited (429)"
    with pytest.raises(SummaryProviderError, match="429"):
        raise SummaryRateLimited(msg)
