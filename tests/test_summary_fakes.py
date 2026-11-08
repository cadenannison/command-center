"""The summary fakes satisfy the ports and behave like docs/contracts/core.md says."""

import asyncio
from datetime import date

import pytest

from command_center.core.errors import SummaryProviderError, SummaryRateLimited
from command_center.core.ports import SummaryProvider, SummaryStore
from command_center.core.summary import DailySummary
from fakes import FakeSummaryProvider, InMemorySummaryStore

DAY = date(2026, 11, 7)


def _summary(headline: str) -> DailySummary:
    return DailySummary(headline=headline)


def test_store_get_returns_none_when_nothing_is_stored() -> None:
    store: SummaryStore = InMemorySummaryStore()

    assert store.get(DAY) is None


def test_store_put_then_get_round_trips() -> None:
    store: SummaryStore = InMemorySummaryStore()

    store.put(DAY, _summary("one"))

    assert store.get(DAY) == _summary("one")


def test_store_put_replaces_the_row_for_that_day() -> None:
    store = InMemorySummaryStore()
    store.put(DAY, _summary("one"))

    store.put(DAY, _summary("two"))

    assert store.get(DAY) == _summary("two")


def test_store_keeps_users_apart() -> None:
    store = InMemorySummaryStore()
    store.put(DAY, _summary("mine"))
    store.put(DAY, _summary("theirs"), user_id="other")

    assert store.get(DAY) == _summary("mine")
    assert store.get(DAY, user_id="other") == _summary("theirs")
    assert store.get(DAY, user_id="nobody") is None


def test_store_latest_is_none_when_empty() -> None:
    assert InMemorySummaryStore().latest_before(date(2026, 12, 31)) is None


def test_store_latest_before_returns_the_greatest_earlier_day_whatever_the_insert_order() -> None:
    store = InMemorySummaryStore()
    store.put(date(2026, 11, 9), _summary("newest"))
    store.put(date(2026, 11, 5), _summary("oldest"))
    store.put(date(2026, 11, 7), _summary("middle"))

    assert store.latest_before(date(2026, 11, 9)) == _summary("middle")
    assert store.latest_before(date(2026, 11, 10)) == _summary("newest")


def test_store_latest_before_is_strict_and_ignores_later_days() -> None:
    store = InMemorySummaryStore()
    store.put(date(2026, 11, 7), _summary("same day"))
    store.put(date(2026, 11, 8), _summary("later"))

    assert store.latest_before(date(2026, 11, 7)) is None


def test_store_latest_before_only_looks_at_the_given_user() -> None:
    store = InMemorySummaryStore()
    store.put(date(2026, 11, 8), _summary("theirs"), user_id="other")
    store.put(date(2026, 11, 5), _summary("mine"))

    assert store.latest_before(date(2026, 11, 20)) == _summary("mine")
    assert store.latest_before(date(2026, 11, 20), user_id="other") == _summary("theirs")


def test_provider_returns_its_summary_and_records_the_prompt() -> None:
    provider: SummaryProvider = FakeSummaryProvider(_summary("hello"))

    result = asyncio.run(provider.summarize("the prompt"))

    assert result == _summary("hello")
    assert isinstance(provider, FakeSummaryProvider)
    assert provider.prompts == ["the prompt"]
    assert provider.calls == 1
    assert provider.name == "fake"


def test_provider_raises_the_error_it_was_given_and_still_records_the_call() -> None:
    provider = FakeSummaryProvider(SummaryRateLimited("rate limited (429)"))

    with pytest.raises(SummaryRateLimited):
        asyncio.run(provider.summarize("p1"))
    with pytest.raises(SummaryRateLimited):
        asyncio.run(provider.summarize("p2"))

    assert provider.prompts == ["p1", "p2"]
    assert provider.calls == 2


def test_provider_accepts_a_plain_provider_error() -> None:
    provider = FakeSummaryProvider(SummaryProviderError("bad key"))

    with pytest.raises(SummaryProviderError, match="bad key"):
        asyncio.run(provider.summarize("p"))
