"""The Gmail card's wording before, during and just after connecting (card G1).

A first-time user should read what is happening, what to do next, how long it takes and what the
card shows when it works, without OAuth, scope or token jargon outside Google's own menu names.
"""

import re

import pytest
from markupsafe import escape

from command_center.core.errors import FatalError
from fake_adapter import FakeAdapter
from settings_ux_support import card, field_tag, make_ux_rig, put
from web_rig import WebRig

CLIENT_JSON = '{"installed":{"client_secret":"fake-client-secret-12345678"}}'
JARGON = ("OAuth", "scope", "token", "JSON")


@pytest.fixture
def rig() -> WebRig:
    return make_ux_rig(("canvas", "gmail"))


def gmail_card(rig: WebRig) -> str:
    return card(rig.client.get("/settings").text, "gmail")


def without_howto(html: str) -> str:
    return re.sub(r'<details class="howto">.*?</details>', "", html, flags=re.DOTALL)


def pending_panel(html: str) -> str:
    match = re.search(r'<div class="pending"[^>]*>.*?</div>', html, flags=re.DOTALL)
    assert match is not None, "no pending panel"
    return match.group(0)


def test_a_card_not_yet_connected_says_what_is_happening_now(rig: WebRig) -> None:
    panel = pending_panel(gmail_card(rig))

    assert "Gmail is not connected yet" in panel
    assert "Nothing is read from your mail" in panel


def test_a_card_not_yet_connected_lists_the_next_steps_in_plain_words(rig: WebRig) -> None:
    panel = pending_panel(gmail_card(rig))

    steps = re.findall(r"<li>(.*?)</li>", panel, flags=re.DOTALL)
    assert len(steps) == 3
    assert "How to connect Gmail" in steps[0]
    assert "paste" in steps[1].lower()
    assert "Connect" in steps[1]
    assert "browser" in steps[2]
    assert "read-only" in steps[2]


def test_a_card_not_yet_connected_says_how_long_it_takes(rig: WebRig) -> None:
    panel = pending_panel(gmail_card(rig))

    assert "about 5 minutes" in panel
    assert "3 minutes" in panel


def test_a_card_not_yet_connected_says_what_it_shows_when_it_works(rig: WebRig) -> None:
    panel = pending_panel(gmail_card(rig))

    assert "“Connected”" in panel
    assert "last checked your mail" in panel


def test_the_card_says_it_only_reads_mail_for_replies_you_owe(rig: WebRig) -> None:
    html = gmail_card(rig)

    assert "only reads your mail" in html
    assert "replies you owe" in html
    assert "never sends, deletes or changes" in html


def test_the_card_says_credentials_are_never_shown_again_after_saving(rig: WebRig) -> None:
    assert "never shown again" in gmail_card(rig)


def test_the_card_says_where_credentials_are_kept_without_naming_the_keychain(rig: WebRig) -> None:
    html = gmail_card(rig)

    assert (
        "stored only on this computer, never in the project folder or any file you commit" in html
    )
    assert "keychain" not in html.lower()


def test_the_card_avoids_jargon_outside_the_collapsible_steps(rig: WebRig) -> None:
    text = re.sub(r"<[^>]+>", " ", without_howto(gmail_card(rig)))

    assert [word for word in JARGON if word in text] == []


def test_the_credentials_box_is_named_in_plain_words(rig: WebRig) -> None:
    html = gmail_card(rig)

    assert "OAuth client JSON" not in html
    assert "Google credentials" in html


def test_the_detailed_steps_stay_in_the_collapsible_how_to(rig: WebRig) -> None:
    html = gmail_card(rig)

    assert '<details class="howto"><summary>How to connect Gmail</summary>' in html
    assert "Test users" in html
    assert "Desktop app" in html


def test_the_waiting_text_says_what_to_do_in_the_browser_and_how_long(rig: WebRig) -> None:
    busy = re.search(r'<span class="busy" id="busy-gmail">(.*?)</span>', gmail_card(rig), re.DOTALL)

    assert busy is not None
    assert "Waiting for Google sign-in…" in busy.group(1)
    assert "browser" in busy.group(1)
    assert "allow read-only access" in busy.group(1)
    assert "3 minutes" in busy.group(1)


def test_a_connected_card_drops_the_not_connected_panel_but_keeps_the_promises() -> None:
    rig = make_ux_rig(("gmail",))
    put(rig, "gmail", client_json=CLIENT_JSON)

    html = gmail_card(rig)

    assert 'class="pending"' not in html
    assert "only reads your mail" in html
    assert "never shown again" in html


def test_a_card_that_is_syncing_says_the_mail_is_being_checked_now() -> None:
    rig = make_ux_rig(("gmail",))
    rig.secrets.set("gmail", "client_json", CLIENT_JSON)
    rig.container.sync.mark_syncing("gmail")

    html = gmail_card(rig)

    assert 'class="pending"' not in html
    assert "Checking your recent mail now" in html
    assert "under a minute" in html
    assert "Signed in" not in html


def test_the_syncing_line_is_absent_once_the_sync_has_finished() -> None:
    rig = make_ux_rig(("gmail",))
    rig.secrets.set("gmail", "client_json", CLIENT_JSON)
    rig.container.sync.record_error("gmail", "Gmail is down")

    assert "Checking your recent mail now" not in gmail_card(rig)


def test_the_status_poll_swaps_the_syncing_line_in_while_syncing() -> None:
    rig = make_ux_rig(("gmail",))
    rig.secrets.set("gmail", "client_json", CLIENT_JSON)
    rig.container.sync.mark_syncing("gmail")

    fragment = rig.client.get("/settings/gmail/status").text

    assert 'id="syncing-note-gmail" hx-swap-oob="true">' in fragment
    assert "Checking your recent mail now" in fragment


def test_the_status_poll_clears_the_syncing_line_when_the_sync_ends() -> None:
    rig = make_ux_rig(("gmail",))
    rig.secrets.set("gmail", "client_json", CLIENT_JSON)
    rig.container.sync.record_error("gmail", "Gmail is down")

    fragment = rig.client.get("/settings/gmail/status").text

    assert 'id="syncing-note-gmail" hx-swap-oob="true" hidden></p>' in fragment
    assert "Checking your recent mail now" not in fragment


def test_a_source_without_a_syncing_line_gets_no_slot_in_the_poll() -> None:
    rig = make_ux_rig(("canvas",))
    rig.secrets.set("canvas", "token", "fake-canvas-token-ABCD1234")
    rig.container.sync.mark_syncing("canvas")

    assert "syncing-note" not in rig.client.get("/settings/canvas/status").text


def test_the_new_panels_are_only_on_the_gmail_card(rig: WebRig) -> None:
    canvas = card(rig.client.get("/settings").text, "canvas")

    assert 'class="pending"' not in canvas
    assert "replies you owe" not in canvas
    assert "Connecting…" in canvas


def test_a_failed_gmail_connect_keeps_the_rules_and_the_panel() -> None:
    adapter = FakeAdapter("gmail", validate_error=FatalError("Google refused the sign-in"))
    rig = make_ux_rig(adapters={"gmail": adapter})

    html = put(rig, "gmail", client_json=CLIENT_JSON)

    assert CLIENT_JSON not in html
    assert "fake-client-secret-12345678" not in html
    assert 'hx-preserve="true"' in field_tag(html, "gmail", "client_json")
    assert "Google refused the sign-in" in html
    assert "Gmail is not connected yet" in html
    assert rig.secrets.get("gmail") == {}


def test_a_stored_gmail_credential_shows_set_and_its_last4_never_the_value() -> None:
    rig = make_ux_rig(("gmail",))
    rig.secrets.set("gmail", "client_json", CLIENT_JSON)

    html = gmail_card(rig)

    assert "fake-client-secret-12345678" not in html
    assert f"ends {escape(CLIENT_JSON[-4:])}" in html
