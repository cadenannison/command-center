"""Today renders without calling the provider, and a provider switch drops today's summary."""

from builders import NOW
from summary_card_support import GOOD, make_card_rig
from web_rig import DENVER, section

TODAY = NOW.astimezone(DENVER).date()


def test_the_first_render_never_calls_the_provider() -> None:
    rig = make_card_rig(enabled=True)

    page = rig.client.get("/").text

    assert rig.provider.calls == 0
    assert 'data-state="generating"' in section(page, "summary-h")


def test_the_first_render_shows_a_cached_summary_without_the_provider() -> None:
    rig = make_card_rig(enabled=True)
    rig.summaries.put(TODAY, GOOD)

    card = section(rig.client.get("/").text, "summary-h")

    assert "Busy Saturday" in card
    assert 'data-state="ready"' in card
    assert rig.provider.calls == 0


def test_the_summary_is_generated_once_and_later_renders_use_the_stored_one() -> None:
    rig = make_card_rig(enabled=True)

    rig.post("/summary/generate")
    card = section(rig.client.get("/").text, "summary-h")

    assert "Busy Saturday" in card
    assert rig.provider.calls == 1


def test_switching_the_provider_drops_todays_cached_summary() -> None:
    rig = make_card_rig(enabled=True)
    rig.summaries.put(TODAY, GOOD)

    rig.post("/summary/settings", {"provider": "ollama"})

    assert rig.summaries.get(TODAY) is None
    assert rig.provider.calls == 0


def test_choosing_the_provider_already_in_use_keeps_the_cached_summary() -> None:
    rig = make_card_rig(enabled=True, provider="gemini")
    rig.summaries.put(TODAY, GOOD)

    rig.post("/summary/settings", {"provider": "gemini"})

    assert rig.summaries.get(TODAY) == GOOD


def test_switching_the_provider_leaves_another_days_summary_alone() -> None:
    rig = make_card_rig(enabled=True)
    yesterday = TODAY.replace(day=TODAY.day - 1)
    rig.summaries.put(yesterday, GOOD)

    rig.post("/summary/settings", {"provider": "ollama"})

    assert rig.summaries.get(yesterday) == GOOD
