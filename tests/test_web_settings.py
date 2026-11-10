"""The settings page: a card per source, write-only fields, connect, polling and delete."""

import re

import pytest

from builders import NOW, make_event
from command_center.core.errors import AuthExpired, SecretStoreError
from command_center.core.schema import ValidationResult
from command_center.services.credential_fields import is_secret
from fake_adapter import KEYCHAIN_DETAIL, FakeAdapter
from fakes import InMemorySecretStore
from web_rig import WebRig, make_rig

SOURCES = ("canvas", "apple_calendar", "learningsuite", "gmail", "weather", "gemini")
CRED = "fake-canvas-token-ABCD1234"
BASE_URL = "https://fake-school.example/secret-path"


@pytest.fixture
def rig() -> WebRig:
    return make_rig(SOURCES)


def card(html: str, source: str) -> str:
    match = re.search(
        rf'<section class="card" id="source-{source}".*?</section>', html, flags=re.DOTALL
    )
    assert match is not None, f"no card for {source}"
    return match.group(0)


def field_tag(html: str, source: str, key: str) -> str:
    match = re.search(rf'<(?:input|textarea) id="f-{source}-{key}"[^>]*>', html)
    assert match is not None, f"no field {key} on {source}"
    return match.group(0)


def put(rig: WebRig, source: str, **fields: str) -> str:
    response = rig.client.put(f"/settings/{source}", data=fields, headers=rig.headers)
    assert response.status_code == 200
    return response.text


def connect_canvas(rig: WebRig, token: str = CRED, base_url: str = BASE_URL) -> str:
    return put(rig, "canvas", base_url=base_url, token=token)


def test_settings_has_one_card_per_registered_source(rig: WebRig) -> None:
    html = rig.client.get("/settings").text

    assert re.findall(r'<section class="card" id="source-(\w+)"', html) == list(SOURCES)


def test_settings_says_so_when_no_source_is_registered() -> None:
    html = make_rig(()).client.get("/settings").text

    assert "No sources are registered" in html


@pytest.mark.parametrize(
    ("source", "key", "tag", "kind"),
    [
        ("canvas", "base_url", "input", "text"),
        ("canvas", "token", "input", "password"),
        ("apple_calendar", "username", "input", "text"),
        ("apple_calendar", "app_password", "input", "password"),
        ("learningsuite", "urls", "textarea", None),
        ("gmail", "client_json", "textarea", None),
        ("weather", "latitude", "input", "text"),
        ("weather", "longitude", "input", "text"),
        ("gemini", "api_key", "input", "password"),
    ],
)
def test_each_source_asks_for_its_own_fields(
    rig: WebRig, source: str, key: str, tag: str, kind: str | None
) -> None:
    field = field_tag(rig.client.get("/settings").text, source, key)

    assert field.startswith(f"<{tag} ")
    assert kind is None or f'type="{kind}"' in field


@pytest.mark.parametrize("source", ["learningsuite", "gmail"])
def test_secret_textareas_are_masked(rig: WebRig, source: str) -> None:
    key = "urls" if source == "learningsuite" else "client_json"

    assert 'class="masked"' in field_tag(rig.client.get("/settings").text, source, key)


def test_cards_only_ask_for_their_own_fields(rig: WebRig) -> None:
    weather = card(rig.client.get("/settings").text, "weather")

    assert re.findall(r'name="(\w+)"', weather) == ["latitude", "longitude"]


def test_a_secret_input_is_never_prefilled(rig: WebRig) -> None:
    connect_canvas(rig)

    token = field_tag(rig.client.get("/settings").text, "canvas", "token")

    assert " value=" not in token
    assert CRED not in token


def test_a_non_secret_input_is_prefilled_with_the_stored_value(rig: WebRig) -> None:
    connect_canvas(rig)

    base_url = field_tag(rig.client.get("/settings").text, "canvas", "base_url")

    assert f'value="{BASE_URL}"' in base_url


def test_gemini_card_states_the_free_tier_caveat(rig: WebRig) -> None:
    gemini = card(rig.client.get("/settings").text, "gemini")

    assert "free tier" in gemini
    assert "never email bodies" in gemini


def test_unset_fields_say_not_set(rig: WebRig) -> None:
    html = card(rig.client.get("/settings").text, "canvas")

    assert html.count("not set") == 2
    assert "Not connected" in html


def test_a_secret_shows_set_and_its_last4_but_a_plain_setting_only_set(rig: WebRig) -> None:
    html = card(connect_canvas(rig), "canvas")

    token_label = re.search(r'for="f-canvas-token">.*?</label>', html, flags=re.DOTALL)
    url_label = re.search(r'for="f-canvas-base_url">.*?</label>', html, flags=re.DOTALL)
    assert token_label is not None
    assert url_label is not None
    assert re.sub(r"\s+", " ", token_label.group(0)).endswith("set · ends 1234</span></label>")
    assert "ends" not in url_label.group(0)
    assert re.search(r">\s*set\s*</span>", url_label.group(0))


def test_a_short_secret_shows_set_without_any_characters(rig: WebRig) -> None:
    html = put(rig, "gemini", api_key="fake-k")

    assert re.search(r">\s*set\s*</span>", html)
    assert "ends" not in html


def test_connect_returns_at_once_with_a_syncing_status_that_polls(rig: WebRig) -> None:
    html = connect_canvas(rig)

    status = re.search(r'<div class="status status-syncing".*?</div>', html, flags=re.DOTALL)
    assert status is not None
    assert 'hx-get="/settings/canvas/status"' in status.group(0)
    assert 'hx-trigger="every 2s"' in status.group(0)
    assert "Syncing…" in status.group(0)


def test_connect_runs_the_sync_afterwards(rig: WebRig) -> None:
    connect_canvas(rig)

    assert len(rig.adapters["canvas"].fetches) == 1


def test_polling_stops_once_the_sync_has_ended(rig: WebRig) -> None:
    connect_canvas(rig)

    fragment = rig.client.get("/settings/canvas/status").text

    assert "Connected: Synced 0 items" in fragment
    assert "hx-get" not in fragment
    assert "hx-trigger" not in fragment


def test_polling_continues_while_the_sync_is_running(rig: WebRig) -> None:
    rig.container.sync.mark_syncing("canvas")

    fragment = rig.client.get("/settings/canvas/status").text

    assert 'hx-trigger="every 2s"' in fragment


def test_connect_button_is_disabled_while_syncing_and_enabled_by_the_final_poll(
    rig: WebRig,
) -> None:
    rig.container.sync.mark_syncing("canvas")
    syncing = rig.client.get("/settings/canvas/status").text
    rig.container.sync.record_error("canvas", "boom")
    ended = rig.client.get("/settings/canvas/status").text

    assert re.search(
        r'<button[^>]*id="connect-canvas"[^>]*hx-swap-oob="true"[^>]* disabled', syncing
    )
    assert re.search(r'<button[^>]*id="connect-canvas"[^>]*hx-swap-oob="true"', ended)
    assert " disabled" not in ended


def test_the_button_says_reconnect_when_the_source_needs_it() -> None:
    rig = make_rig(adapters={"canvas": FakeAdapter("canvas", script=[AuthExpired("expired")])})
    connect_canvas(rig)

    fragment = rig.client.get("/settings/canvas/status").text
    page = rig.client.get("/settings").text

    assert ">Reconnect</button>" in fragment
    assert ">Reconnect</button>" in card(page, "canvas")
    assert "Reconnect needed" in card(page, "canvas")


def test_the_button_says_connect_otherwise(rig: WebRig) -> None:
    assert ">Connect</button>" in card(rig.client.get("/settings").text, "canvas")


def test_a_failed_sync_shows_an_error_status(rig: WebRig) -> None:
    rig.container.sync.record_error("canvas", "Canvas is down")

    assert "Error: Canvas is down" in card(rig.client.get("/settings").text, "canvas")


def test_gmail_connect_shows_waiting_for_google_and_allows_a_long_request(rig: WebRig) -> None:
    gmail = card(rig.client.get("/settings").text, "gmail")

    assert "Waiting for Google sign-in…" in gmail
    timeout = int(re.search(r'hx-request=\'\{"timeout": (\d+)\}\'', gmail).group(1))  # type: ignore[union-attr]
    assert timeout >= 600_000


def test_other_sources_do_not_mention_google(rig: WebRig) -> None:
    canvas = card(rig.client.get("/settings").text, "canvas")

    assert "Google" not in canvas
    assert "Connecting…" in canvas


def test_the_form_refuses_a_double_submit_in_the_browser(rig: WebRig) -> None:
    canvas = card(rig.client.get("/settings").text, "canvas")

    assert 'hx-sync="this:drop"' in canvas
    assert 'hx-disabled-elt="#connect-canvas"' in canvas
    assert 'hx-indicator="#busy-canvas"' in canvas


def test_a_blank_field_keeps_the_stored_value(rig: WebRig) -> None:
    connect_canvas(rig)

    put(rig, "canvas", base_url="", token="fake-canvas-token-NEWW5678")  # noqa: S106  (fake- test value)

    assert rig.secrets.get("canvas") == {
        "base_url": BASE_URL,
        "token": "fake-canvas-token-NEWW5678",
    }
    assert rig.adapters["canvas"].validations[-1] == {
        "base_url": BASE_URL,
        "token": "fake-canvas-token-NEWW5678",
    }


def test_surrounding_whitespace_is_trimmed(rig: WebRig) -> None:
    put(rig, "canvas", token=f"  {CRED}\n")

    assert rig.secrets.get("canvas") == {"token": CRED}


def test_fields_the_source_does_not_have_are_ignored(rig: WebRig) -> None:
    put(rig, "canvas", token=CRED, api_key="fake-other-key-12345678")

    assert rig.secrets.get("canvas") == {"token": CRED}


def test_a_blank_submit_on_an_unconfigured_source_does_not_reach_the_service(rig: WebRig) -> None:
    html = put(rig, "canvas", base_url="", token="")

    assert "Fill in the fields to connect." in html
    assert rig.adapters["canvas"].validations == []


def test_a_blank_submit_on_a_configured_source_validates_the_stored_credentials(
    rig: WebRig,
) -> None:
    connect_canvas(rig)

    put(rig, "canvas", token="")

    assert rig.adapters["canvas"].validations[-1] == {"base_url": BASE_URL, "token": CRED}


def test_a_value_over_the_limit_is_refused_without_saving(rig: WebRig) -> None:
    html = put(rig, "canvas", token="x" * 8193)

    assert "longer than 8192 characters" in html
    assert rig.secrets.get("canvas") == {}
    assert rig.adapters["canvas"].validations == []


def test_rejected_credentials_show_the_reason_and_store_nothing() -> None:
    rejected = ValidationResult(ok=False, message="Canvas said the token is invalid")
    rig = make_rig(adapters={"canvas": FakeAdapter("canvas", validation=rejected)})

    html = connect_canvas(rig)

    assert "Canvas said the token is invalid" in html
    assert rig.secrets.get("canvas") == {}
    assert "status-syncing" not in html
    assert rig.adapters["canvas"].fetches == []


def test_delete_removes_the_keys_and_the_sources_events(rig: WebRig) -> None:
    connect_canvas(rig)
    rig.seed(make_event(id="x", title="Canvas item", start=NOW))

    html = rig.client.delete("/settings/canvas", headers=rig.headers).text

    assert rig.secrets.get("canvas") == {}
    assert "Canvas item" not in rig.client.get("/").text
    assert "Not connected" in html
    assert html.count("not set") == 2


def test_every_card_has_a_delete_button_that_confirms(rig: WebRig) -> None:
    html = rig.client.get("/settings").text

    assert (
        len(re.findall(r'hx-delete="/settings/\w+"[^>]*hx-confirm="Delete the stored', html)) == 6
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [("put", "/settings/nope"), ("delete", "/settings/nope"), ("get", "/settings/nope/status")],
)
def test_an_unknown_source_is_a_404(rig: WebRig, method: str, path: str) -> None:
    response = rig.client.request(method, path, headers=rig.headers)

    assert response.status_code == 404


def test_no_credential_value_appears_in_any_response() -> None:
    values = {
        "canvas": {"base_url": BASE_URL, "token": CRED},
        "apple_calendar": {
            "username": "fake-user@example.test",
            "app_password": "fake-abcd-efgh-ijkl",
        },
        "learningsuite": {"urls": "https://fake-feed.example/ical/fake-feed-key-0001"},
        "gmail": {"client_json": '{"installed":{"client_secret":"fake-client-secret-12345678"}}'},
        "weather": {"latitude": "40.123456", "longitude": "-111.654321"},
        "gemini": {"api_key": "fake-gemini-key-WXYZ9876"},
    }
    rig = make_rig(SOURCES)
    seen = [put(rig, source, **fields) for source, fields in values.items()]
    seen += [rig.client.get(path).text for path in ("/", "/week", "/month", "/settings")]
    seen += [rig.client.get(f"/settings/{source}/status").text for source in SOURCES]
    seen.append(rig.client.delete("/settings/canvas", headers=rig.headers).text)
    seen.append(put(rig, "canvas", token=""))
    secrets = [
        value
        for source, fields in values.items()
        for key, value in fields.items()
        if is_secret(source, key)
    ]
    assert len(secrets) == 5  # the plain settings (URL, Apple ID, coordinates) may be shown
    assert len(seen) > 10

    leaked = [
        (v, i) for v in secrets for i, body in enumerate(seen) if v in body or _json_form(v) in body
    ]

    assert leaked == []


def test_nothing_secret_is_in_a_header_or_cookie(rig: WebRig) -> None:
    response = rig.client.put("/settings/canvas", data={"token": CRED}, headers=rig.headers)

    assert CRED not in str(response.headers)
    assert "set-cookie" not in response.headers


def _json_form(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&#34;").replace("<", "&lt;")


class DeleteFailsStore(InMemorySecretStore):
    """A keychain that reads and writes but cannot delete."""

    def delete(self, source: str, *, user_id: str = "local") -> None:  # noqa: ARG002
        raise SecretStoreError(KEYCHAIN_DETAIL)


def test_delete_does_not_claim_success_when_the_secret_store_cannot_delete() -> None:
    rig = make_rig(("canvas",), secrets=DeleteFailsStore())
    connect_canvas(rig)

    html = rig.client.delete("/settings/canvas", headers=rig.headers).text

    assert "Deleted." not in html
    assert "secret store unavailable" in html
    assert rig.secrets.get("canvas") != {}
