"""The phone read policy, proven by sending a request to every registered GET route (card 09).

test_remote_policy.py compares a hand-kept table with the policy function. Here each GET route is
requested as a paired device through the real middleware, with the allowlist from api/policy.py as
the only oracle, so a route added without a policy decision fails by name.
"""

import pytest

from auth_rig import AuthRig, make_auth_rig
from command_center.api.policy import REMOTE_DENIED_READS, REMOTE_READS, refusal_status
from route_support import Endpoint, walk

OPEN_WITHOUT_A_TOKEN = {"/v1/health"}
GET_ROUTES = [e for e in walk(make_auth_rig().app.routes) if e.method == "GET"]
IDS = [e.template for e in GET_ROUTES]


def _on_list(endpoint: Endpoint) -> bool:
    return endpoint.template in REMOTE_READS


def _phone_get(rig: AuthRig, endpoint: Endpoint) -> tuple[int, str]:
    response = rig.remote.get(endpoint.path, headers=rig.bearer(rig.pair_phone().access_token))
    return response.status_code, response.text


@pytest.mark.parametrize("endpoint", GET_ROUTES, ids=IDS)
def test_a_paired_phone_gets_the_denial_exactly_when_the_route_is_off_the_list(
    endpoint: Endpoint,
) -> None:
    if endpoint.template in OPEN_WITHOUT_A_TOKEN:
        pytest.skip("open without a token; covered by the no-token test")
    rig = make_auth_rig()

    status, body = _phone_get(rig, endpoint)

    denial = refusal_status(endpoint.path)
    if _on_list(endpoint):
        # the handler may answer 404 for a sample id; it must not be the policy's own refusal
        assert "A paired phone may not do this" not in body, endpoint
        assert status != 403, endpoint
    else:
        assert status == denial, (endpoint, status)
        expected = "A paired phone may not do this" if denial == 403 else "Not Found"
        assert expected in body, (endpoint, body)


@pytest.mark.parametrize("endpoint", GET_ROUTES, ids=IDS)
def test_without_a_token_every_route_but_the_open_one_is_401(endpoint: Endpoint) -> None:
    rig = make_auth_rig()

    status = rig.remote.get(endpoint.path).status_code

    assert status == (200 if endpoint.template in OPEN_WITHOUT_A_TOKEN else 401), endpoint


def test_every_registered_get_route_is_exercised() -> None:
    rig = make_auth_rig()
    exercised = [e for e in walk(rig.app.routes) if e.method == "GET"]

    assert exercised == GET_ROUTES
    assert len(exercised) == len(IDS) > 0
    assert {"/v1/tasks", "/v1/history", "/v1/settings", "/v1/devices", "/static"} <= set(IDS)


def test_the_allowlist_names_only_routes_the_app_serves() -> None:
    assert set(REMOTE_READS) <= set(IDS)
    assert set(REMOTE_DENIED_READS) <= set(IDS)


def test_a_get_route_registered_later_and_not_listed_is_refused() -> None:
    rig = make_auth_rig()

    @rig.app.get("/v1/added-later")
    def added() -> dict[str, str]:
        return {"value": "fake-added-later"}

    status, body = _phone_get(rig, Endpoint("GET", "/v1/added-later"))

    assert status == 403
    assert "fake-added-later" not in body
