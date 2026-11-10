"""The Today summary card: every state, the enable switch, and that off sends nothing."""

import re

import pytest

from command_center.core.errors import SummaryProviderError, SummaryRateLimited
from summary_card_support import GOOD, CardRig, make_card_rig
from web_rig import section

NOT_ENABLED = "The AI summary is not enabled."


def card(rig: CardRig) -> str:
    return section(rig.client.get("/").text, "summary-h")


def state_of(html: str) -> str:
    found = re.search(r'data-state="([a-z_]+)"', html)
    assert found is not None
    return found.group(1)


def test_off_explains_the_opt_in_and_what_is_sent_and_offers_enable() -> None:
    html = card(make_card_rig())

    assert NOT_ENABLED in html
    assert "titles and due dates" in html
    assert "Email bodies are never sent" in html
    assert "Enable AI summary" in html
    assert state_of(html) == "off"


def test_off_calls_no_provider_even_when_the_page_is_loaded() -> None:
    rig = make_card_rig()

    card(rig)

    assert (rig.provider.calls, rig.built) == (0, [])


def test_off_without_a_control_has_no_enable_button() -> None:
    html = card(make_card_rig(with_control=False))

    assert NOT_ENABLED in html
    assert "Enable AI summary" not in html


def test_enabling_through_the_card_returns_the_generating_state_without_calling_the_provider() -> (
    None
):
    rig = make_card_rig()

    html = rig.post("/summary/settings?date=2026-11-07", {"enabled": "on", "provider": "gemini"})

    assert state_of(html) == "generating"
    assert "Generating summary" in html
    assert 'hx-post="/summary/generate?date=2026-11-07&amp;refresh=false"' in html
    assert rig.provider.calls == 0


def test_the_generating_cards_request_fills_the_card_with_the_summary() -> None:
    rig = make_card_rig(enabled=True)

    html = rig.post("/summary/generate?date=2026-11-07")

    assert state_of(html) == "ready"
    assert all(t in html for t in ("Busy Saturday", "Priorities: Finish essay", "Quiz Monday"))
    assert "Regenerate" in html


def test_an_enabled_page_shows_the_result_and_a_regenerate_button() -> None:
    rig = make_card_rig(enabled=True)
    rig.post("/summary/generate")

    html = card(rig)

    assert state_of(html) == "ready"
    assert "Busy Saturday" in html
    assert 'hx-post="/summary/generate?date=2026-11-07&amp;refresh=true"' in html


def test_regenerate_asks_the_provider_again() -> None:
    rig = make_card_rig(enabled=True)
    rig.post("/summary/generate")

    rig.post("/summary/generate?date=2026-11-07&refresh=true")

    assert rig.provider.calls == 2


def test_gemini_without_a_key_links_to_the_gemini_card_and_calls_nothing() -> None:
    rig = make_card_rig(enabled=True, key=False)

    html = card(rig)

    assert state_of(html) == "no_key"
    assert 'href="/settings#source-gemini"' in html
    assert rig.provider.calls == 0


def test_ollama_needs_no_key() -> None:
    rig = make_card_rig(enabled=True, provider="ollama", key=False)

    assert state_of(rig.post("/summary/generate")) == "ready"


@pytest.mark.parametrize(
    ("failure", "shown"),
    [
        (SummaryProviderError("boom fake-secret-ABCD1234"), "Summary unavailable right now."),
        (SummaryRateLimited("429 fake-secret-ABCD1234"), "limiting requests"),
        (RuntimeError("boom fake-secret-ABCD1234"), "Summary unavailable right now."),
    ],
)
def test_a_provider_failure_shows_a_redacted_error_with_a_retry(
    failure: Exception, shown: str
) -> None:
    rig = make_card_rig(failure, enabled=True)

    html = rig.post("/summary/generate")

    assert state_of(html) == "error"
    assert shown in html
    assert "fake-secret" not in html
    assert "Try again" in html


def test_turning_it_off_sends_nothing_afterwards() -> None:
    rig = make_card_rig(enabled=True)
    card(rig)
    calls = rig.provider.calls

    html = rig.post("/summary/settings?date=2026-11-07", {"enabled": "off"})
    page = card(rig)
    rig.post("/summary/generate?date=2026-11-07&refresh=true")

    assert state_of(html) == "off"
    assert state_of(page) == "off"
    assert rig.provider.calls == calls


def test_the_choice_survives_in_the_store_not_the_environment_default() -> None:
    rig = make_card_rig(enabled=False)

    rig.post("/summary/settings?date=2026-11-07", {"enabled": "on"})

    assert rig.settings_store.get("summary.enabled") == "on"


def test_changing_the_provider_builds_it_and_regenerates() -> None:
    rig = make_card_rig(enabled=True, key=False)

    html = rig.post("/summary/settings?date=2026-11-07", {"provider": "ollama"})

    assert rig.settings_store.get("summary.provider") == "ollama"
    assert "refresh=true" in html


def test_an_unknown_provider_is_a_400_and_changes_nothing() -> None:
    rig = make_card_rig()

    response = rig.client.post(
        "/summary/settings", data={"provider": "openai"}, headers=rig.headers
    )

    assert response.status_code == 400
    assert rig.settings_store.get("summary.provider") is None


def test_a_garbled_switch_is_a_400_and_does_not_change_the_provider_either() -> None:
    rig = make_card_rig()

    response = rig.client.post(
        "/summary/settings", data={"enabled": "true", "provider": "ollama"}, headers=rig.headers
    )

    assert response.status_code == 400
    assert rig.settings_store.get("summary.provider") is None
    assert rig.settings_store.get("summary.enabled") is None


def test_settings_cannot_be_changed_without_a_control() -> None:
    rig = make_card_rig(with_control=False)

    response = rig.client.post("/summary/settings", data={"enabled": "on"}, headers=rig.headers)

    assert response.status_code == 404


def test_the_routes_refuse_a_request_without_the_csrf_token() -> None:
    rig = make_card_rig()

    response = rig.client.post("/summary/settings", data={"enabled": "on"})

    assert response.status_code == 403
    assert rig.settings_store.get("summary.enabled") is None


def test_the_api_route_follows_the_stored_switch() -> None:
    rig = make_card_rig(enabled=True)
    rig.post("/summary/settings?date=2026-11-07", {"enabled": "off"})

    assert rig.container.summary is None
    assert GOOD.headline not in rig.client.get("/").text
