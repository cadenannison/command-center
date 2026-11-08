"""SummaryService with a fake provider: cache, fallbacks, opt-in email, prompt contents."""

import asyncio
from datetime import date, timedelta

import pytest

from builders import NOW, make_event
from command_center.core.errors import SummaryProviderError, SummaryRateLimited
from command_center.core.summary import DailySummary
from fakes import FakeSummaryProvider
from summary_support import GOOD, OLD, Rig

TODAY = date(2026, 11, 7)  # NOW is 05:00 on this day in America/Denver
ADDRESS = "fake-person@example.com"


def rig_with_event(outcome: DailySummary | Exception = GOOD, *, include_email: bool = False) -> Rig:
    rig = Rig(provider=_provider(outcome), include_email=include_email)
    rig.events.upsert(
        [make_event(id="meeting", title="Team meeting", start=NOW + timedelta(hours=2))]
    )
    return rig


def _provider(outcome: DailySummary | Exception) -> FakeSummaryProvider:
    return FakeSummaryProvider(outcome)


# ---- cache ----------------------------------------------------------------------------------


async def test_first_call_asks_the_provider_and_stores_the_answer() -> None:
    rig = rig_with_event()
    result = await rig.service.get(TODAY)
    assert (result.summary, result.provider, result.cached) == (GOOD, "fake", False)
    assert rig.provider.calls == 1
    assert rig.store.get(TODAY) == GOOD


async def test_second_call_is_a_cache_hit_and_does_not_call_the_provider() -> None:
    rig = rig_with_event()
    service = rig.service
    await service.get(TODAY)
    again = await service.get(TODAY)
    assert (again.summary, again.provider, again.cached) == (GOOD, "fake", True)
    assert rig.provider.calls == 1


async def test_a_stored_summary_is_returned_without_building_a_prompt() -> None:
    rig = rig_with_event()
    rig.store.put(TODAY, OLD)
    result = await rig.service.get(TODAY)
    assert (result.summary, result.cached) == (OLD, True)
    assert rig.provider.calls == 0


async def test_each_day_has_its_own_cache_entry() -> None:
    rig = rig_with_event()
    rig.store.put(TODAY - timedelta(days=1), OLD)
    result = await rig.service.get(TODAY)
    assert (result.summary, result.cached) == (GOOD, False)


async def test_concurrent_requests_for_one_day_call_the_provider_once() -> None:
    rig = rig_with_event()
    service = rig.service
    results = await asyncio.gather(service.get(TODAY), service.get(TODAY), service.get(TODAY))
    assert rig.provider.calls == 1
    assert sorted(r.cached for r in results) == [False, True, True]


# ---- fallback -------------------------------------------------------------------------------


@pytest.mark.parametrize("error", [SummaryProviderError("down"), SummaryRateLimited("slow down")])
async def test_provider_failure_without_a_stored_summary_falls_back_to_the_template(
    error: SummaryProviderError,
) -> None:
    rig = rig_with_event(error)
    result = await rig.service.get(TODAY)
    assert result.summary.headline == "1 item to look at on 2026-11-07"
    assert result.summary.priorities == ["Team meeting"]
    assert (result.provider, result.cached) == ("template", False)


@pytest.mark.parametrize("error", [SummaryProviderError("down"), SummaryRateLimited("slow down")])
async def test_provider_failure_returns_the_last_stored_summary(
    error: SummaryProviderError,
) -> None:
    rig = rig_with_event(error)
    rig.store.put(TODAY - timedelta(days=3), OLD)
    result = await rig.service.get(TODAY)
    assert (result.summary, result.provider, result.cached) == (OLD, "stored", True)


async def test_the_stored_fallback_is_never_from_a_later_day() -> None:
    rig = rig_with_event(SummaryProviderError("down"))
    rig.store.put(TODAY + timedelta(days=1), OLD)
    result = await rig.service.get(TODAY)
    assert (result.provider, result.cached) == ("template", False)
    assert result.summary != OLD


async def test_a_fallback_is_not_stored_so_the_next_request_retries() -> None:
    rig = rig_with_event(SummaryProviderError("down"))
    service = rig.service
    await service.get(TODAY)
    assert rig.store.get(TODAY) is None
    await service.get(TODAY)
    assert rig.provider.calls == 2


async def test_a_bug_in_the_provider_is_not_swallowed() -> None:
    rig = rig_with_event(RuntimeError("bug"))
    with pytest.raises(RuntimeError):
        await rig.service.get(TODAY)


async def test_a_day_with_nothing_to_say_skips_the_provider() -> None:
    rig = Rig(provider=_provider(GOOD))
    result = await rig.service.get(TODAY)
    assert (result.provider, result.cached) == ("template", False)
    assert result.summary.headline == "Nothing scheduled for 2026-11-07"
    assert rig.provider.calls == 0
    assert rig.store.get(TODAY) is None


# ---- what reaches the provider --------------------------------------------------------------


async def test_an_email_address_in_a_subject_never_reaches_the_prompt() -> None:
    for include_email in (True, False):
        rig = rig_with_event(include_email=include_email)
        rig.events.upsert(
            [
                make_event(
                    id="mail", kind="email", title=f"Re: send it to {ADDRESS} please", start=NOW
                )
            ]
        )
        await rig.service.get(TODAY)
        prompt = rig.provider.prompts[0]
        assert ADDRESS not in prompt
        assert "example.com" not in prompt


async def test_an_email_address_in_an_event_title_never_reaches_the_prompt() -> None:
    rig = rig_with_event()
    rig.events.upsert([make_event(id="call", title=f"Call {ADDRESS}", start=NOW)])
    await rig.service.get(TODAY)
    assert ADDRESS not in rig.provider.prompts[0]
    assert "[email]" in rig.provider.prompts[0]


async def test_email_is_left_out_unless_opted_in() -> None:
    off = rig_with_event()
    off.events.upsert([make_event(id="m", kind="email", title="Lunch plans", start=NOW)])
    await off.service.get(TODAY)
    assert "Lunch plans" not in off.provider.prompts[0]
    assert "Team meeting" in off.provider.prompts[0]

    on = rig_with_event(include_email=True)
    on.events.upsert([make_event(id="m", kind="email", title="Lunch plans", start=NOW)])
    await on.service.get(TODAY)
    assert "- [email] Lunch plans" in on.provider.prompts[0]


async def test_email_never_reaches_the_template_unless_opted_in() -> None:
    rig = Rig(provider=_provider(SummaryProviderError("down")))
    rig.events.upsert([make_event(id="m", kind="email", title="Lunch plans", start=NOW)])
    result = await rig.service.get(TODAY)
    assert result.provider == "template"
    assert result.summary.headline == "Nothing scheduled for 2026-11-07"


async def test_sender_and_body_data_in_raw_never_reaches_the_prompt() -> None:
    rig = rig_with_event(include_email=True)
    rig.events.upsert(
        [
            make_event(
                id="m",
                kind="email",
                title="Hello",
                start=NOW,
                raw={"from": "fake-sender@example.org", "body": "private body text"},
            )
        ]
    )
    await rig.service.get(TODAY)
    prompt = rig.provider.prompts[0]
    assert "fake-sender" not in prompt
    assert "private body text" not in prompt


async def test_due_dates_are_the_users_local_day() -> None:
    rig = Rig(provider=_provider(GOOD))
    # 03:00 UTC on the 8th is 20:00 on the 7th in Denver.
    due = NOW.replace(day=8, hour=3)
    rig.events.upsert([make_event(id="hw", kind="assignment", title="Essay", due=due)])
    await rig.service.get(TODAY)
    assert "- [assignment] Essay (due 2026-11-07)" in rig.provider.prompts[0]


async def test_todays_summary_includes_urgent_items_from_outside_the_day() -> None:
    rig = Rig(provider=_provider(GOOD))
    due = NOW + timedelta(hours=20)  # tomorrow in Denver, but due within 24h: needs attention
    rig.events.upsert([make_event(id="hw", kind="assignment", title="Urgent essay", due=due)])
    rig.events.upsert([make_event(id="m", title="Today thing", start=NOW + timedelta(hours=1))])
    await rig.service.get(TODAY)
    assert "Urgent essay" in rig.provider.prompts[0]


async def test_another_days_summary_does_not_borrow_todays_attention_list() -> None:
    rig = Rig(provider=_provider(GOOD))
    due = NOW + timedelta(hours=20)
    rig.events.upsert([make_event(id="hw", kind="assignment", title="Urgent essay", due=due)])
    past = TODAY - timedelta(days=2)
    rig.events.upsert([make_event(id="old", title="Old thing", start=NOW - timedelta(days=2))])
    await rig.service.get(past)
    assert "Urgent essay" not in rig.provider.prompts[0]
    assert "Old thing" in rig.provider.prompts[0]


# ---- text for the web page ------------------------------------------------------------------


async def test_for_day_renders_the_summary_as_text() -> None:
    rig = rig_with_event()
    assert await rig.service.for_day(TODAY) == "Busy day\nPriorities: Essay\nHeads up: Quiz Friday"
