"""GET /v1/geocode: candidates, empty results, bad queries, limits, failures and who may call it."""

import json
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient

from auth_rig import REMOTE, make_auth_rig
from command_center.adapters.weather_geocode import URL, OpenMeteoGeocoder
from command_center.api import create_app
from command_center.core.errors import FatalError, TransientError
from command_center.services.geocode import SEARCH_LIMIT, GeocodeService
from geocode_support import TYPED_QUERY, FakeGeocoder, make_geocode_rig, place

SPRINGFIELDS = [
    place("Springfield", "Missouri", latitude=37.21533, longitude=-93.29824, population=169_176),
    place("Springfield", "Illinois", latitude=39.80172, longitude=-89.64371, population=114_394),
    place("Springfield", "Massachusetts", latitude=42.10148, longitude=-72.58981, population=None),
]


def test_an_ambiguous_name_lists_every_candidate_and_picks_none() -> None:
    rig = make_geocode_rig(SPRINGFIELDS)

    response = rig.client.get("/v1/geocode", params={"q": "Springfield"})

    assert response.status_code == 200
    body = response.json()
    assert [item["region"] for item in body] == ["Missouri", "Illinois", "Massachusetts"]
    assert set(body[0]) == {"name", "region", "country", "latitude", "longitude", "population"}
    assert body[0]["latitude"] == 37.21533
    assert body[2]["population"] is None


def test_no_results_is_200_with_an_empty_list() -> None:
    rig = make_geocode_rig([])

    response = rig.client.get("/v1/geocode", params={"q": "Qqqqqq"})

    assert (response.status_code, response.json()) == (200, [])


def test_the_answer_is_not_cached() -> None:
    rig = make_geocode_rig()

    response = rig.client.get("/v1/geocode", params={"q": "Provo"})

    assert response.headers["cache-control"] == "no-store"


def test_the_query_is_trimmed_before_it_is_searched() -> None:
    rig = make_geocode_rig()

    _ = rig.client.get("/v1/geocode", params={"q": "  Provo  "})

    assert rig.geocoder.queries == ["Provo"]


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "a"}, {"q": "   "}, {"q": "x" * 101}])
def test_a_missing_or_badly_sized_query_is_422_that_never_echoes_the_input(
    params: dict[str, str],
) -> None:
    rig = make_geocode_rig()

    response = rig.client.get("/v1/geocode", params=params)

    assert response.status_code == 422
    assert all(set(issue) == {"loc", "msg", "type"} for issue in response.json()["detail"])
    assert "x" * 20 not in response.text
    assert rig.geocoder.queries == []


def test_the_eleventh_search_in_a_minute_is_429_with_retry_after() -> None:
    rig = make_geocode_rig()
    for _ in range(SEARCH_LIMIT):
        assert rig.client.get("/v1/geocode", params={"q": "Provo"}).status_code == 200

    response = rig.client.get("/v1/geocode", params={"q": "Provo"})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert response.json() == {"detail": "Too many city searches; try again in 60 seconds"}
    assert len(rig.geocoder.queries) == SEARCH_LIMIT


@pytest.mark.parametrize("error", [TransientError, FatalError])
def test_a_provider_failure_is_502_with_a_message_that_is_redacted(
    error: type[Exception],
) -> None:
    rig = make_geocode_rig(error("Open-Meteo wrote to ada@example.com about 87654321"))

    response = rig.client.get("/v1/geocode", params={"q": TYPED_QUERY})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail.startswith("City search failed: Open-Meteo wrote to")
    assert "ada@example.com" not in detail
    assert "87654321" not in detail


def test_a_transient_provider_failure_is_502_too() -> None:
    rig = make_geocode_rig(TransientError("Open-Meteo city search is unavailable (503)"))

    response = rig.client.get("/v1/geocode", params={"q": "Provo"})

    assert response.status_code == 502
    assert response.json() == {
        "detail": "City search failed: Open-Meteo city search is unavailable (503)"
    }


def test_without_a_geocoder_the_route_is_404() -> None:
    rig = make_geocode_rig(wired=False)

    response = rig.client.get("/v1/geocode", params={"q": "Provo"})

    assert (response.status_code, response.json()) == (
        404,
        {"detail": "City search is not available"},
    )


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def test_end_to_end_over_the_real_adapter_and_a_faked_open_meteo(
    router: respx.MockRouter,
) -> None:
    rig = make_geocode_rig()
    container = replace(rig.container, geocode=GeocodeService(OpenMeteoGeocoder(), rig.clock))
    client = TestClient(create_app(container), base_url="http://localhost")
    reply = {
        "results": [
            {
                "name": "Provo",
                "latitude": 40.23384,
                "longitude": -111.65853,
                "admin1": "Utah",
                "country": "United States",
                "population": 115_000,
            },
        ]
    }
    _ = router.get(URL).respond(json=reply)

    response = client.get("/v1/geocode", params={"q": "Provo"})

    assert response.json() == [
        {
            "name": "Provo",
            "region": "Utah",
            "country": "United States",
            "latitude": 40.23384,
            "longitude": -111.65853,
            "population": 115_000,
        }
    ]


def test_a_paired_phone_is_refused_and_nothing_is_searched() -> None:
    rig = make_auth_rig()
    geocoder = FakeGeocoder()
    container = replace(rig.container, geocode=GeocodeService(geocoder, rig.clock))
    app = create_app(container, remote_hosts=(REMOTE,))
    remote = TestClient(app, base_url=f"https://{REMOTE}")
    phone = rig.pair_phone()

    response = remote.get(
        "/v1/geocode", params={"q": "Provo"}, headers=rig.bearer(phone.access_token)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "A paired phone may not do this"}
    assert geocoder.queries == []


def test_a_tailnet_caller_with_no_token_is_401() -> None:
    rig = make_auth_rig()

    assert rig.remote.get("/v1/geocode", params={"q": "Provo"}).status_code == 401


def test_the_loopback_web_ui_origin_may_search() -> None:
    rig = make_geocode_rig()

    assert rig.client.get("/v1/geocode", params={"q": "Provo"}).status_code == 200


def test_the_schema_documents_the_candidate_and_every_failure() -> None:
    rig = make_geocode_rig()
    spec: dict[str, Any] = create_app(rig.container).openapi()

    operation = spec["paths"]["/v1/geocode"]["get"]
    assert set(operation["responses"]) == {"200", "404", "422", "429", "502"}
    assert "Retry-After" in json.dumps(operation["responses"]["429"])
    assert set(spec["components"]["schemas"]["GeocodeCandidate"]["properties"]) == {
        "name",
        "region",
        "country",
        "latitude",
        "longitude",
        "population",
    }
