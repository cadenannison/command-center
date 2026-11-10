"""The weather card's "Find a city" box: candidates, failure states, fill, and what is saved."""

import logging
import re
from dataclasses import dataclass, replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from command_center.core.errors import FatalError, TransientError
from command_center.core.geocode import GeocodeCandidate
from command_center.services.geocode import SEARCH_LIMIT, GeocodeService
from command_center.web import create_router
from fakes import FakeClock, InMemorySecretStore
from geocode_support import NOW, TYPED_QUERY, FakeGeocoder, place
from web_rig import CSRF, LOCAL, WebRig, make_rig

SPRINGFIELDS = [
    place("Springfield", "Missouri", latitude=37.21533, longitude=-93.29824, population=169_176),
    place("Springfield", "Illinois", latitude=39.80172, longitude=-89.64371, population=114_394),
    place("Springfield", "Massachusetts", latitude=42.10148, longitude=-72.58981, population=None),
]
CANVAS_TOKEN = "fake-canvas-token-ABCD1234"  # noqa: S105  (fake- test value)
OOB_INPUT = re.compile(r'<input id="f-weather-(\w+)"[^>]*value="([^"]*)"[^>]*hx-swap-oob="true"')


@dataclass
class CityRig:
    web: WebRig
    client: TestClient
    geocoder: FakeGeocoder
    secrets: InMemorySecretStore


def make_city_rig(
    outcome: list[GeocodeCandidate] | Exception | None = None, *, wired: bool = True
) -> CityRig:
    web = make_rig(("canvas", "weather", "gemini"))
    geocoder = FakeGeocoder(outcome)
    service = GeocodeService(geocoder, FakeClock(NOW)) if wired else None
    container = replace(web.container, geocode=service)
    app = FastAPI()
    app.include_router(create_router(container, csrf_token=CSRF))
    return CityRig(web, TestClient(app, base_url=LOCAL), geocoder, web.secrets)


def search(rig: CityRig, text: str = "Springfield") -> str:
    response = rig.client.put(
        "/settings/weather", data={"action": "search", "city": text}, headers=rig.web.headers
    )
    assert response.status_code == 200
    return response.text


def fill(rig: CityRig, **fields: str) -> str:
    response = rig.client.put(
        "/settings/weather", data={"action": "fill", **fields}, headers=rig.web.headers
    )
    assert response.status_code == 200
    return response.text


def weather_card(rig: CityRig) -> str:
    html = rig.client.get("/settings").text
    match = re.search(r'<section class="card" id="source-weather".*?</section>', html, re.DOTALL)
    assert match is not None
    return match.group(0)


def test_the_weather_card_has_a_find_a_city_box_and_the_other_cards_do_not() -> None:
    rig = make_city_rig()
    html = rig.client.get("/settings").text

    assert '<form class="city-search"' in weather_card(rig)
    assert html.count('<form class="city-search"') == 1
    assert html.count('name="city"') == 1


def test_the_search_goes_in_a_put_body_so_the_query_is_never_in_a_url() -> None:
    rig = make_city_rig()
    card = weather_card(rig)
    form = re.search(r'<form class="city-search".*?</form>', card, re.DOTALL)

    assert form is not None
    assert 'hx-put="/settings/weather"' in form.group(0)
    assert "hx-get" not in card
    assert "hx-post" not in form.group(0)
    assert not re.search(r'hx-(?:put|get|post)="[^"]*\?', card)


def test_the_search_keeps_the_csrf_token_like_the_other_forms() -> None:
    rig = make_city_rig()
    page = rig.client.get("/settings").text
    refused = rig.client.put("/settings/weather", data={"action": "search", "city": "Provo"})

    assert f'"X-CSRF-Token": "{CSRF}"' in page  # the body's hx-headers cover every form in it
    assert refused.status_code == 403
    assert rig.geocoder.queries == []


def test_an_ambiguous_name_lists_every_candidate_and_picks_none() -> None:
    rig = make_city_rig(SPRINGFIELDS)

    html = search(rig)

    assert html.count("Use these coordinates") == 3
    for text in ("Missouri", "Illinois", "Massachusetts", "United States", "population 169,176"):
        assert text in html
    assert "population 114,394" in html
    assert OOB_INPUT.findall(html) == []  # no coordinate input was touched
    assert "Nothing is saved until you press Connect" in html


def test_at_most_five_candidates_are_shown() -> None:
    rig = make_city_rig([place(f"Town {i}") for i in range(9)])

    assert search(rig, "Town").count("Use these coordinates") == 5


def test_a_candidate_button_sends_its_own_coordinates_in_the_body() -> None:
    rig = make_city_rig(SPRINGFIELDS)

    html = search(rig)

    assert 'hx-put="/settings/weather"' in html
    assert "&#34;latitude&#34;: &#34;39.80172&#34;" in html or '"latitude": "39.80172"' in html
    assert "hx-get" not in html


def test_no_results_says_so() -> None:
    rig = make_city_rig([])

    html = search(rig, "Qqqqqq")

    assert "No places matched" in html
    assert "Use these coordinates" not in html


def test_a_query_too_short_is_not_sent_to_the_geocoder() -> None:
    rig = make_city_rig()

    assert "at least 2 characters" in search(rig, " a ")
    assert "at most 100 characters" in search(rig, "x" * 101)
    assert rig.geocoder.queries == []


@pytest.mark.parametrize("error", [TransientError, FatalError])
def test_a_provider_failure_shows_a_redacted_message(error: type[Exception]) -> None:
    detail = (
        f"unreachable https://geocoding-api.example/v1/search?name={TYPED_QUERY} fake-tok-123456"
    )
    rig = make_city_rig(error(detail))

    html = search(rig, TYPED_QUERY)

    assert "City search failed" in html
    assert TYPED_QUERY not in html
    assert "geocoding-api.example" not in html
    assert 'class="flash bad"' in html


def test_the_eleventh_search_in_a_minute_is_refused_with_the_wait() -> None:
    rig = make_city_rig()
    for _ in range(SEARCH_LIMIT):
        assert "Too many searches" not in search(rig, "Provo")

    html = search(rig, "Provo")

    assert "Too many searches" in html
    assert re.search(r"Wait \d+ seconds", html)
    assert len(rig.geocoder.queries) == SEARCH_LIMIT


def test_a_container_without_a_geocoder_says_the_search_is_not_available() -> None:
    rig = make_city_rig(wired=False)

    html = search(rig, "Provo")

    assert "City search is not available" in html
    assert "latitude and longitude yourself" in html


def test_search_and_fill_are_refused_for_a_source_without_a_city_search() -> None:
    rig = make_city_rig()

    for action in ("search", "fill"):
        response = rig.client.put(
            "/settings/canvas", data={"action": action, "city": "Provo"}, headers=rig.web.headers
        )
        assert response.status_code == 422
    assert rig.geocoder.queries == []


def test_fill_puts_the_chosen_coordinates_in_the_two_inputs_and_saves_nothing() -> None:
    rig = make_city_rig()

    html = fill(rig, latitude="39.80172", longitude="-89.64371", label="Springfield, Illinois")

    assert dict(OOB_INPUT.findall(html)) == {"latitude": "39.80172", "longitude": "-89.64371"}
    assert "Filled in Springfield, Illinois" in html
    assert "Nothing is saved until you press Connect" in html
    assert rig.secrets.get("weather") == {}
    assert rig.web.adapters["weather"].validations == []


def test_the_filled_inputs_keep_the_shape_of_the_card_inputs() -> None:
    rig = make_city_rig()
    original = re.search(r'<input id="f-weather-latitude"[^>]*>', weather_card(rig))
    filled = re.search(
        r'<input id="f-weather-latitude"[^>]*>', fill(rig, latitude="1", longitude="2")
    )

    assert original is not None
    assert filled is not None
    assert 'name="latitude"' in filled.group(0)
    assert 'type="text"' in filled.group(0)
    assert 'placeholder="40.2338"' in filled.group(0)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [("91", "0"), ("0", "181"), ("nan", "0"), ("0", "inf"), ("north", "0"), ("", "0")],
)
def test_fill_refuses_coordinates_that_are_not_valid(latitude: str, longitude: str) -> None:
    rig = make_city_rig()

    html = fill(rig, latitude=latitude, longitude=longitude)

    assert "not valid" in html
    assert OOB_INPUT.findall(html) == []
    assert rig.secrets.get("weather") == {}


def test_a_label_is_escaped_in_the_fill_answer() -> None:
    rig = make_city_rig()

    html = fill(rig, latitude="1", longitude="2", label="<script>alert(1)</script>")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_nothing_is_saved_until_the_form_is_submitted() -> None:
    rig = make_city_rig(SPRINGFIELDS)

    _ = search(rig)
    _ = fill(rig, latitude="39.80172", longitude="-89.64371")

    assert rig.secrets.get("weather") == {}

    connected = rig.client.put(
        "/settings/weather",
        data={"latitude": "39.80172", "longitude": "-89.64371"},
        headers=rig.web.headers,
    )

    assert connected.status_code == 200
    assert rig.secrets.get("weather") == {"latitude": "39.80172", "longitude": "-89.64371"}


def test_the_city_input_is_never_stored_as_a_credential() -> None:
    rig = make_city_rig()

    response = rig.client.put(
        "/settings/weather",
        data={"city": TYPED_QUERY, "latitude": "40.2338", "longitude": "-111.6585"},
        headers=rig.web.headers,
    )

    assert response.status_code == 200
    assert rig.secrets.get("weather") == {"latitude": "40.2338", "longitude": "-111.6585"}
    assert rig.web.adapters["weather"].validations == [
        {"latitude": "40.2338", "longitude": "-111.6585"}
    ]
    assert TYPED_QUERY not in response.text
    assert TYPED_QUERY not in rig.client.get("/settings").text
    assert rig.geocoder.queries == []


def test_the_typed_query_reaches_no_log_record(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    failing = make_city_rig(TransientError(f"timeout for {TYPED_QUERY}"))
    limited = make_city_rig()
    saved = make_city_rig()

    for rig in (failing, limited, saved):
        _ = search(rig, TYPED_QUERY)
    for _ in range(SEARCH_LIMIT):
        _ = search(limited, TYPED_QUERY)
    _ = saved.client.put(
        "/settings/weather",
        data={"city": TYPED_QUERY, "latitude": "1", "longitude": "2"},
        headers=saved.web.headers,
    )

    assert any("city search" in record.getMessage() for record in caplog.records)
    assert TYPED_QUERY not in caplog.text


def test_the_page_and_every_answer_contain_no_secret_value() -> None:
    rig = make_city_rig(SPRINGFIELDS)
    rig.client.put(
        "/settings/canvas",
        data={"base_url": "https://fake-school.example", "token": CANVAS_TOKEN},
        headers=rig.web.headers,
    )
    rig.secrets.set("gemini", "api_key", "fake-gemini-key-WXYZ9876")

    pages = [
        rig.client.get("/settings").text,
        rig.client.get("/").text,
        search(rig),
        fill(rig, latitude="1", longitude="2"),
    ]

    for html in pages:
        assert CANVAS_TOKEN not in html
        assert "fake-gemini-key-WXYZ9876" not in html
        assert CSRF not in html.replace(f'"X-CSRF-Token": "{CSRF}"', "")


def test_the_weather_card_credits_open_meteo_and_links_the_licence_and_terms() -> None:
    card = weather_card(make_city_rig())

    assert re.search(
        r'<a href="https://open-meteo\.com/"[^>]*>Weather data by Open-Meteo\.com</a>', card
    )
    assert 'href="https://open-meteo.com/en/licence"' in card
    assert 'href="https://open-meteo.com/en/terms"' in card
    assert "CC BY 4.0" in card
    assert "GeoNames" in card


def test_the_today_footer_links_the_terms_beside_the_pinned_credit() -> None:
    html = make_city_rig().client.get("/").text

    assert re.search(
        r'<a href="https://open-meteo\.com/"[^>]*>Weather data by Open-Meteo\.com</a>', html
    )
    assert 'href="https://open-meteo.com/en/terms"' in html
    assert 'href="https://open-meteo.com/en/licence"' in html
