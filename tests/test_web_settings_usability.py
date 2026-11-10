"""The settings page: prefilled plain fields, failed submits, unverified saves, actions, how-tos."""

import re
from datetime import timedelta

import pytest

from command_center.core.errors import AuthExpired, FatalError, TransientError
from command_center.services.credential_fields import is_secret
from command_center.services.settings import UNVERIFIED_PREFIX
from command_center.web.sources import SOURCE_FORMS
from fake_adapter import FakeAdapter
from settings_ux_support import card, field_tag, make_ux_rig, put
from web_rig import WebRig

SOURCES = ("canvas", "apple_calendar", "learningsuite", "gmail", "weather", "gemini")
TOKEN = "fake-canvas-token-ABCD1234"  # noqa: S105  (fake- test value)
BAD = "fake-bad-token-ZZZZ9999"
URL = "https://fake-school.example"
NEW_URL = "https://fake-other.example"


def failing_rig(error: Exception) -> WebRig:
    return make_ux_rig(adapters={"canvas": FakeAdapter("canvas", validate_error=error)})


def store_good(rig: WebRig) -> None:
    rig.secrets.set("canvas", "token", TOKEN)
    rig.secrets.set("canvas", "base_url", URL)


def test_every_form_field_is_secret_exactly_when_the_services_list_says_so() -> None:
    mismatched = [
        (source, f.key)
        for source, form in SOURCE_FORMS.items()
        for f in form.fields
        if f.secret != is_secret(source, f.key)
    ]

    assert mismatched == []


@pytest.mark.parametrize(
    ("source", "key", "value"),
    [
        ("canvas", "base_url", URL),
        ("apple_calendar", "username", "fake-user@example.test"),
        ("weather", "latitude", "40.2338"),
        ("weather", "longitude", "-111.6585"),
    ],
)
def test_the_form_is_prefilled_with_the_stored_plain_value(
    source: str, key: str, value: str
) -> None:
    rig = make_ux_rig(SOURCES)
    rig.secrets.set(source, key, value)

    tag = field_tag(rig.client.get("/settings").text, source, key)

    assert f'value="{value}"' in tag


@pytest.mark.parametrize(
    ("source", "key", "value"),
    [
        ("canvas", "token", TOKEN),
        ("apple_calendar", "app_password", "fake-abcd-efgh-ijkl"),
        ("learningsuite", "urls", "https://fake-feed.example/ical/fake-feed-key-0001"),
        ("gmail", "client_json", '{"installed":{"client_secret":"fake-client-secret-1234"}}'),
        ("gemini", "api_key", "fake-gemini-key-WXYZ9876"),
    ],
)
def test_a_stored_secret_is_never_in_the_page(source: str, key: str, value: str) -> None:
    rig = make_ux_rig(SOURCES)
    rig.secrets.set(source, key, value)

    html = rig.client.get("/settings").text

    assert value not in html
    assert " value=" not in field_tag(html, source, key)


@pytest.mark.parametrize(
    "error", [AuthExpired("no"), TransientError("offline"), FatalError("bad url")]
)
def test_a_failed_connect_keeps_the_stored_credentials(error: Exception) -> None:
    rig = failing_rig(error)
    store_good(rig)

    put(rig, "canvas", base_url=NEW_URL, token=BAD)

    assert dict(rig.secrets.get("canvas")) == {"token": TOKEN, "base_url": URL}


def test_a_failed_connect_keeps_the_typed_plain_value_in_the_form_not_the_stored_one() -> None:
    rig = failing_rig(AuthExpired("no"))
    store_good(rig)

    html = card(put(rig, "canvas", base_url=NEW_URL, token=BAD), "canvas")

    assert f'value="{NEW_URL}"' in field_tag(html, "canvas", "base_url")
    assert URL not in html


def test_a_failed_connect_never_echoes_the_typed_secret() -> None:
    rig = failing_rig(AuthExpired("no"))

    html = put(rig, "canvas", base_url=NEW_URL, token=BAD)

    assert BAD not in html
    assert " value=" not in field_tag(html, "canvas", "token")
    assert "Credentials were rejected" in html


def test_a_typed_plain_value_is_escaped_when_it_is_shown_back() -> None:
    rig = failing_rig(AuthExpired("no"))

    html = put(rig, "canvas", base_url='"><script>alert(1)</script>', token=BAD)

    assert "<script>alert(1)" not in html


def test_the_browser_is_told_to_keep_its_secret_inputs_after_a_failed_connect() -> None:
    rig = failing_rig(AuthExpired("no"))

    html = put(rig, "canvas", base_url=NEW_URL, token=BAD)

    assert 'hx-preserve="true"' in field_tag(html, "canvas", "token")
    assert "hx-preserve" not in field_tag(html, "canvas", "base_url")


def test_a_fresh_page_does_not_ask_the_browser_to_keep_anything() -> None:
    rig = make_ux_rig()

    assert "hx-preserve" not in rig.client.get("/settings").text


@pytest.mark.parametrize(
    ("error", "offered"),
    [(TransientError("offline"), True), (AuthExpired("no"), False), (FatalError("bad url"), False)],
)
def test_save_anyway_is_offered_only_after_a_transient_failure(
    error: Exception,
    offered: bool,  # noqa: FBT001
) -> None:
    rig = failing_rig(error)

    html = put(rig, "canvas", base_url=URL, token=TOKEN)

    assert ("Save anyway (unverified)" in html) is offered


def test_save_anyway_is_not_offered_on_a_fresh_page_or_after_success() -> None:
    rig = make_ux_rig()

    assert "Save anyway" not in rig.client.get("/settings").text
    assert "Save anyway" not in put(rig, "canvas", base_url=URL, token=TOKEN)


def test_save_anyway_sends_the_form_with_the_unverified_action() -> None:
    rig = failing_rig(TransientError("offline"))

    html = put(rig, "canvas", base_url=URL, token=TOKEN)

    button = re.search(r"<button[^>]*>Save anyway \(unverified\)</button>", html)
    assert button is not None
    assert "&#34;action&#34;" in button.group(0) or '"action": "unverified"' in button.group(0)
    assert 'hx-include="#form-canvas"' in button.group(0)


def test_saving_unverified_stores_the_values_without_checking_or_syncing() -> None:
    rig = failing_rig(TransientError("offline"))

    html = put(rig, "canvas", action="unverified", base_url=URL, token=TOKEN)

    assert dict(rig.secrets.get("canvas")) == {"token": TOKEN, "base_url": URL}
    assert (rig.adapters["canvas"].validations, rig.adapters["canvas"].fetches) == ([], [])
    assert UNVERIFIED_PREFIX in html
    assert TOKEN not in html


def test_an_unverified_save_shows_needs_attention() -> None:
    rig = failing_rig(TransientError("offline"))
    put(rig, "canvas", action="unverified", base_url=URL, token=TOKEN)

    html = rig.client.get("/settings").text

    assert "Needs attention" in card(html, "canvas")
    assert "status-syncing" not in html


def test_an_unverified_save_with_nothing_typed_and_nothing_stored_is_refused() -> None:
    rig = make_ux_rig()

    html = put(rig, "canvas", action="unverified")

    assert "Fill in the fields to connect." in html
    assert rig.secrets.get("canvas") == {}


def test_an_unknown_action_is_a_422() -> None:
    rig = make_ux_rig()

    response = rig.client.put(
        "/settings/canvas", data={"action": "fake-nope-1234"}, headers=rig.headers
    )

    assert response.status_code == 422
    assert "fake-nope-1234" not in response.text


def test_sync_now_can_be_pressed_again_once_the_sync_has_ended() -> None:
    rig = make_ux_rig()
    store_good(rig)

    put(rig, "canvas", action="sync")
    html = put(rig, "canvas", action="sync")

    assert "Sync started" in html
    assert len(rig.adapters["canvas"].fetches) == 2


def test_test_connection_and_sync_now_are_offered_only_once_something_is_stored() -> None:
    rig = make_ux_rig()
    before = card(rig.client.get("/settings").text, "canvas")
    store_good(rig)
    after = card(rig.client.get("/settings").text, "canvas")

    assert ("Test connection" in before, "Sync now" in before) == (False, False)
    assert ("Test connection" in after, "Sync now" in after) == (True, True)


def test_a_credential_only_integration_offers_test_connection_but_not_sync_now() -> None:
    rig = make_ux_rig(("canvas",), integrations={"gemini": FakeAdapter("gemini")})
    rig.secrets.set("gemini", "api_key", "fake-gemini-key-WXYZ9876")

    gemini = card(rig.client.get("/settings").text, "gemini")

    assert "Test connection" in gemini
    assert "Sync now" not in gemini


def test_test_connection_answers_with_the_result_only() -> None:
    rig = make_ux_rig()
    store_good(rig)

    html = put(rig, "canvas", action="test")

    assert 'id="result-canvas"' in html
    assert "Connected" in html
    assert "<section" not in html
    assert rig.adapters["canvas"].validations == [{"token": TOKEN, "base_url": URL}]


def test_test_connection_changes_no_sync_state_and_starts_no_sync() -> None:
    rig = make_ux_rig()
    store_good(rig)

    put(rig, "canvas", action="test")

    assert rig.container.sync.state("canvas") is None
    assert rig.adapters["canvas"].fetches == []


def test_test_connection_shows_a_redacted_failure() -> None:
    rig = failing_rig(TransientError("cannot reach me@example.test 123456789"))
    store_good(rig)

    html = put(rig, "canvas", action="test")

    assert "me@example.test" not in html
    assert "123456789" not in html
    assert "flash bad" in html


def test_test_connection_with_nothing_stored_says_to_connect_first() -> None:
    rig = make_ux_rig()

    html = put(rig, "canvas", action="test")

    assert "Nothing is stored for this source yet" in html
    assert rig.adapters["canvas"].validations == []


def test_sync_now_runs_a_sync_and_answers_with_a_polling_status() -> None:
    rig = make_ux_rig()
    store_good(rig)

    html = put(rig, "canvas", action="sync")

    assert len(rig.adapters["canvas"].fetches) == 1
    assert "Sync started" in html
    status = re.search(r'<div class="status status-syncing"[^>]*>', html)
    assert status is not None
    assert 'hx-swap-oob="true"' in status.group(0)
    assert 'hx-get="/settings/canvas/status"' in status.group(0)


def test_sync_now_with_nothing_stored_is_refused() -> None:
    rig = make_ux_rig()

    html = put(rig, "canvas", action="sync")

    assert "Connect this source first" in html
    assert rig.adapters["canvas"].fetches == []


def test_sync_now_is_refused_while_a_sync_is_running() -> None:
    rig = make_ux_rig()
    store_good(rig)
    rig.container.sync.mark_syncing("canvas")

    html = put(rig, "canvas", action="sync")

    assert "already running" in html
    assert rig.adapters["canvas"].fetches == []


def test_sync_now_is_refused_for_an_integration() -> None:
    rig = make_ux_rig(("canvas",), integrations={"gemini": FakeAdapter("gemini")})
    rig.secrets.set("gemini", "api_key", "fake-gemini-key-WXYZ9876")

    html = put(rig, "gemini", action="sync")

    assert "no items to sync" in html


def test_no_secret_appears_in_any_response_of_any_action() -> None:
    rig = failing_rig(TransientError("offline"))
    store_good(rig)
    seen = [
        put(rig, "canvas", base_url=NEW_URL, token=BAD),
        put(rig, "canvas", action="unverified", base_url=NEW_URL, token=BAD),
        put(rig, "canvas", action="test"),
        put(rig, "canvas", action="sync"),
        rig.client.get("/settings").text,
        rig.client.get("/settings/canvas/status").text,
    ]

    assert [(s, i) for s in (TOKEN, BAD) for i, body in enumerate(seen) if s in body] == []


def checklist_item(html: str, source: str) -> str:
    match = re.search(rf'<li><a href="#source-{source}">.*?</li>', html, flags=re.DOTALL)
    assert match is not None, f"no checklist line for {source}"
    return re.sub(r"\s+", " ", match.group(0))


def test_the_checklist_comes_before_the_cards_and_lists_every_source() -> None:
    rig = make_ux_rig(SOURCES)

    html = rig.client.get("/settings").text

    assert html.index('id="h-checklist"') < html.index('id="source-canvas"')
    assert [s for s in SOURCES if f'<a href="#source-{s}">' in html] == list(SOURCES)


def test_the_checklist_says_not_connected_for_a_source_with_nothing_stored() -> None:
    rig = make_ux_rig()

    line = checklist_item(rig.client.get("/settings").text, "canvas")

    assert "chip-not_connected" in line
    assert "Not connected" in line


def test_the_checklist_says_connected_with_the_time_of_the_last_sync() -> None:
    rig = make_ux_rig()
    store_good(rig)
    put(rig, "canvas", action="sync")
    rig.clock.advance(timedelta(minutes=3))

    line = checklist_item(rig.client.get("/settings").text, "canvas")

    assert "chip-connected" in line
    assert "last sync 3 min ago" in line


def test_the_checklist_says_needs_attention_after_a_failed_sync() -> None:
    rig = make_ux_rig(adapters={"canvas": FakeAdapter("canvas", script=[AuthExpired("expired")])})
    store_good(rig)
    put(rig, "canvas", action="sync")

    line = checklist_item(rig.client.get("/settings").text, "canvas")

    assert "chip-needs_attention" in line
    assert "last attempt" in line


@pytest.mark.parametrize("source", SOURCES)
def test_every_card_has_a_collapsible_how_to_without_javascript(source: str) -> None:
    html = card(make_ux_rig(SOURCES).client.get("/settings").text, source)

    assert re.search(r'<details class="howto"><summary>How to connect [^<]+</summary>', html)
    assert "<li>" in html
    assert "<script" not in html


def howto_text(source: str) -> str:
    html = card(make_ux_rig(SOURCES).client.get("/settings").text, source)
    match = re.search(r'<details class="howto">.*?</details>', html, flags=re.DOTALL)
    assert match is not None
    return match.group(0)


def test_the_canvas_how_to_covers_the_url_and_the_token_and_admits_menus_may_differ() -> None:
    text = howto_text("canvas")

    assert "Approved Integrations" in text
    assert "New Access Token" in text
    assert "https://school.instructure.com" in text
    assert "may differ" in text


def test_the_gemini_how_to_names_ai_studio() -> None:
    assert "https://aistudio.google.com/apikey" in howto_text("gemini")


def test_the_gmail_how_to_covers_the_test_user_and_the_desktop_client() -> None:
    text = howto_text("gmail")

    assert "Test users" in text
    assert "Desktop app" in text
    assert "may differ" in text
