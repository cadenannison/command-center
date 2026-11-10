"""SummaryService.generate: the loud variant the web card uses (no fallback), and summary_text."""

from datetime import date, timedelta

import pytest

from builders import NOW, make_event
from command_center.core.errors import SummaryProviderError, SummaryRateLimited
from command_center.core.summary import DailySummary
from command_center.services.errors import SummaryUnavailableError
from command_center.services.summary import summary_text
from fakes import FakeSummaryProvider
from summary_support import GOOD, OLD, Rig

TODAY = date(2026, 11, 7)


def rig_with_event(outcome: DailySummary | Exception = GOOD) -> Rig:
    rig = Rig(provider=FakeSummaryProvider(outcome))
    rig.events.upsert([make_event(id="m", title="Team meeting", start=NOW + timedelta(hours=2))])
    return rig


async def test_generate_stores_and_returns_the_providers_summary() -> None:
    rig = rig_with_event()

    result = await rig.service.generate(TODAY)

    assert (result.summary, result.cached, rig.store.get(TODAY)) == (GOOD, False, GOOD)


async def test_generate_serves_the_stored_summary_without_a_provider_call() -> None:
    rig = rig_with_event()
    rig.store.put(TODAY, OLD)

    result = await rig.service.generate(TODAY)

    assert (result.summary, result.cached, rig.provider.calls) == (OLD, True, 0)


async def test_refresh_asks_the_provider_again_and_replaces_the_stored_summary() -> None:
    rig = rig_with_event()
    rig.store.put(TODAY, OLD)

    result = await rig.service.generate(TODAY, refresh=True)

    assert (result.summary, rig.provider.calls, rig.store.get(TODAY)) == (GOOD, 1, GOOD)


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (SummaryProviderError("boom fake-secret-ABCD1234"), "failed"),
        (SummaryRateLimited("429 fake-secret-ABCD1234"), "rate_limited"),
    ],
)
async def test_a_provider_failure_raises_with_a_reason_and_never_the_providers_text(
    failure: Exception, reason: str
) -> None:
    rig = rig_with_event(failure)

    with pytest.raises(SummaryUnavailableError) as raised:
        await rig.service.generate(TODAY)

    assert raised.value.reason == reason
    assert "fake-secret" not in str(raised.value)


async def test_a_failed_refresh_keeps_the_stored_summary() -> None:
    rig = rig_with_event(SummaryProviderError("down"))
    rig.store.put(TODAY, OLD)

    with pytest.raises(SummaryUnavailableError):
        await rig.service.generate(TODAY, refresh=True)

    assert rig.store.get(TODAY) == OLD


async def test_a_day_with_nothing_on_it_gets_the_template_without_a_provider_call() -> None:
    rig = Rig(provider=FakeSummaryProvider(GOOD))

    result = await rig.service.generate(TODAY)

    assert (result.provider, rig.provider.calls) == ("template", 0)


def test_summary_text_lists_the_headline_priorities_and_heads_up() -> None:
    assert summary_text(GOOD) == "Busy day\nPriorities: Essay\nHeads up: Quiz Friday"
