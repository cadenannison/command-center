"""OpenMeteoGeocoder over a respx-mocked geocoding API."""

import logging
from collections.abc import Iterator

import httpx
import pytest
import respx

from command_center.adapters.weather_geocode import TIMEOUT_SECONDS, URL, OpenMeteoGeocoder
from command_center.core.errors import FatalError, TransientError
from command_center.core.geocode import MAX_CANDIDATES
from geocode_support import TYPED_QUERY


def hit(name: str, admin1: str | None, **fields: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": 4_409_896,
        "name": name,
        "latitude": 37.2153,
        "longitude": -93.2982,
        "elevation": 394.0,
        "feature_code": "PPLA2",
        "country_code": "US",
        "admin1": admin1,
        "timezone": "America/Chicago",
        "population": 169_176,
        "country": "United States",
    }
    body.update(fields)
    return body


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


async def test_an_ambiguous_name_returns_every_candidate_in_the_providers_order(
    router: respx.MockRouter,
) -> None:
    states = ["Missouri", "Illinois", "Massachusetts", "Oregon", "Ohio"]
    _ = router.get(URL).respond(
        json={
            "results": [
                hit("Springfield", state, latitude=30 + i) for i, state in enumerate(states)
            ]
        }
    )

    found = await OpenMeteoGeocoder().search("Springfield")

    assert [item.region for item in found] == states
    assert {item.name for item in found} == {"Springfield"}
    first = found[0]
    assert (first.country, first.latitude, first.longitude, first.population) == (
        "United States",
        30.0,
        -93.2982,
        169_176,
    )


async def test_the_request_asks_for_five_english_results_by_name(router: respx.MockRouter) -> None:
    route = router.get(URL).respond(json={"results": [hit("Provo", "Utah")]})

    _ = await OpenMeteoGeocoder().search("Provo")

    params = route.calls.last.request.url.params
    assert params["name"] == "Provo"
    assert params["count"] == str(MAX_CANDIDATES)
    assert params["language"] == "en"


async def test_no_results_is_an_empty_list_not_an_error(router: respx.MockRouter) -> None:
    _ = router.get(URL).respond(json={"generationtime_ms": 0.4})  # the key is absent, as sent

    assert await OpenMeteoGeocoder().search("Qqqqqq") == []


async def test_a_place_with_no_region_or_population_is_still_a_candidate(
    router: respx.MockRouter,
) -> None:
    _ = router.get(URL).respond(
        json={"results": [{"name": "Nowhere", "latitude": 1.5, "longitude": 2.5}]}
    )

    [only] = await OpenMeteoGeocoder().search("Nowhere")

    assert (only.region, only.country, only.population) == (None, None, None)


async def test_more_than_five_results_are_cut_to_five(router: respx.MockRouter) -> None:
    _ = router.get(URL).respond(json={"results": [hit(f"Town {i}", "X") for i in range(8)]})

    assert len(await OpenMeteoGeocoder().search("Town")) == MAX_CANDIDATES


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_busy_or_broken_provider_is_transient(
    router: respx.MockRouter, status: int
) -> None:
    _ = router.get(URL).respond(status)

    with pytest.raises(TransientError, match=str(status)):
        _ = await OpenMeteoGeocoder().search(TYPED_QUERY)


@pytest.mark.parametrize("status", [400, 404, 301])
async def test_any_other_status_is_fatal(router: respx.MockRouter, status: int) -> None:
    _ = router.get(URL).respond(status)

    with pytest.raises(FatalError, match=str(status)):
        _ = await OpenMeteoGeocoder().search("Provo")


@pytest.mark.parametrize(
    "body",
    [b"not json", b'{"results": "x"}', b'{"results": [{"name": "A"}]}'],
)
async def test_a_malformed_reply_is_fatal(router: respx.MockRouter, body: bytes) -> None:
    _ = router.get(URL).respond(200, content=body)

    with pytest.raises(FatalError, match="unexpected response"):
        _ = await OpenMeteoGeocoder().search("Provo")


async def test_a_coordinate_off_the_globe_is_fatal(router: respx.MockRouter) -> None:
    _ = router.get(URL).respond(json={"results": [hit("Moon", None, latitude=123.0)]})

    with pytest.raises(FatalError, match="unexpected response"):
        _ = await OpenMeteoGeocoder().search("Moon")


async def test_a_network_failure_is_transient_and_names_no_query(
    router: respx.MockRouter,
) -> None:
    _ = router.get(URL).mock(side_effect=httpx.ConnectError(f"cannot reach {TYPED_QUERY}"))

    with pytest.raises(TransientError) as caught:
        _ = await OpenMeteoGeocoder().search(TYPED_QUERY)

    assert TYPED_QUERY not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


async def test_no_error_message_carries_the_query(router: respx.MockRouter) -> None:
    for status in (429, 400):
        _ = router.get(URL).respond(status)
        with pytest.raises((TransientError, FatalError)) as caught:
            _ = await OpenMeteoGeocoder().search(TYPED_QUERY)
        assert TYPED_QUERY not in str(caught.value)


async def test_an_injected_client_is_used_with_an_explicit_timeout(
    router: respx.MockRouter,
) -> None:
    route = router.get(URL).respond(json={"results": [hit("Provo", "Utah")]})
    async with httpx.AsyncClient() as client:
        found = await OpenMeteoGeocoder(client=client).search("Provo")

    assert len(found) == 1
    assert route.calls.last.request.extensions["timeout"]["read"] == TIMEOUT_SECONDS


async def test_the_query_text_reaches_no_log_record(
    router: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    _ = router.get(URL).respond(json={"results": [hit("Provo", "Utah")]})
    caplog.set_level(logging.DEBUG)

    _ = await OpenMeteoGeocoder().search(TYPED_QUERY)
    router.get(URL).respond(500)
    with pytest.raises(TransientError):
        _ = await OpenMeteoGeocoder().search(TYPED_QUERY)

    assert TYPED_QUERY not in caplog.text
    assert all(TYPED_QUERY not in record.getMessage() for record in caplog.records)
