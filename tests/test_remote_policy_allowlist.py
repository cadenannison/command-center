"""A paired phone may read only what is listed: default deny (decision 0412).

The table in test_remote_policy.py classifies the routes that exist today. This file proves the
rule itself: a route nobody listed is refused, matching is by whole path segment, and the list is
exactly the one the project manager confirmed.
"""

import pytest

from auth_rig import make_auth_rig
from command_center.api.policy import REMOTE_DENIED_READS, REMOTE_READS, remote_may_call

CONFIRMED_READS = {
    "/v1/tasks",
    "/v1/dashboards",
    "/v1/dashboards/{dashboard_id}",
    "/v1/display-settings",
    "/v1/agenda/{period}",
    "/v1/events",
    "/v1/attention",
    "/v1/summary",
    "/v1/needs-me",
}
DENIAL = {"detail": "A paired phone may not do this"}


def sample(template: str) -> str:
    return template.replace("{dashboard_id}", "fake-dashboard").replace("{period}", "day")


def test_the_read_allowlist_is_exactly_the_confirmed_list() -> None:
    assert set(REMOTE_READS) == CONFIRMED_READS


@pytest.mark.parametrize("template", sorted(CONFIRMED_READS))
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_every_listed_read_is_allowed_for_get_and_head(template: str, method: str) -> None:
    assert remote_may_call(method, sample(template)) is True


@pytest.mark.parametrize("template", sorted(CONFIRMED_READS))
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_listed_read_is_not_a_listed_write(template: str, method: str) -> None:
    assert remote_may_call(method, sample(template)) is False


def test_a_route_added_later_and_not_listed_is_refused_for_a_phone() -> None:
    rig = make_auth_rig()
    ran: list[str] = []

    @rig.app.get("/v1/scratch-new-read")
    def scratch() -> dict[str, str]:
        ran.append("handler")
        return {"secret": "fake-scratch-value"}

    phone = rig.pair_phone()

    refused = rig.remote.get("/v1/scratch-new-read", headers=rig.bearer(phone.access_token))
    served = rig.local.get("/v1/scratch-new-read")

    assert refused.status_code == 403
    assert refused.json() == DENIAL
    assert "fake-scratch-value" not in refused.text
    assert ran == ["handler"]  # only the loopback call below it reached the handler
    assert served.status_code == 200  # loopback is unchanged


@pytest.mark.parametrize(
    "path",
    [
        "/v1/dashboardsX",
        "/v1/tasksX",
        "/v1/tasks/",
        "/v1/tasks/x",
        "/v1/tasks/../settings",
        "/v1/dashboards/",
        "/v1/dashboards/a/b",
        "/v1/dashboards/..",
        "/v1/dashboards/.",
        "/v1/agenda",
        "/v1/agenda/",
        "/v1/agenda/day/extra",
        "/v1/agenda/../settings",
        "/v1/events/x",
        "//v1/tasks",
        "/v1/TASKS",
        "v1/tasks",
        "",
        "/",
    ],
)
def test_matching_is_by_whole_path_segment(path: str) -> None:
    assert remote_may_call("GET", path) is False


def test_a_templated_entry_matches_exactly_one_segment() -> None:
    assert remote_may_call("GET", "/v1/dashboards/fake-id") is True
    assert remote_may_call("GET", "/v1/agenda/week") is True
    assert remote_may_call("GET", "/v1/dashboards/fake-id/extra") is False


@pytest.mark.parametrize("path", ["/v1/geocode", "/v1/chat/context-preview"])
def test_the_geocoder_and_the_chat_preview_stay_denied(path: str) -> None:
    assert path in REMOTE_DENIED_READS
    assert remote_may_call("GET", path) is False


def test_the_geocoder_and_the_chat_preview_answer_a_phone_403() -> None:
    rig = make_auth_rig()
    headers = rig.bearer(rig.pair_phone().access_token)

    for path in ("/v1/geocode?q=Paris", "/v1/chat/context-preview"):
        response = rig.remote.get(path, headers=headers)
        assert response.status_code == 403, path
        assert response.json() == DENIAL


@pytest.mark.parametrize(
    "path",
    [
        "/v1/history",
        "/v1/settings",
        "/v1/devices",
        "/v1/dashboardsX",
        "/v1/geocode",
    ],
)
def test_a_phone_with_a_token_is_refused_every_unlisted_v1_read_with_403(path: str) -> None:
    rig = make_auth_rig()
    response = rig.remote.get(path, headers=rig.bearer(rig.pair_phone().access_token))
    assert response.status_code == 403
    assert response.json() == DENIAL


@pytest.mark.parametrize("path", ["/", "/week", "/month", "/history", "/openapi.json", "/docs"])
def test_a_phone_with_a_token_is_refused_the_web_pages_and_the_docs_with_404(path: str) -> None:
    rig = make_auth_rig()
    response = rig.remote.get(path, headers=rig.bearer(rig.pair_phone().access_token))
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_a_phone_without_a_token_still_gets_401_on_an_unlisted_read() -> None:
    rig = make_auth_rig()
    assert rig.remote.get("/v1/history").status_code == 401
    assert rig.remote.get("/v1/scratch-unknown").status_code == 401


def test_a_listed_read_is_served_to_a_phone_with_a_token() -> None:
    rig = make_auth_rig()
    headers = rig.bearer(rig.pair_phone().access_token)
    for path in ("/v1/tasks", "/v1/needs-me", "/v1/events", "/v1/display-settings"):
        assert rig.remote.get(path, headers=headers).status_code not in {401, 403}, path
