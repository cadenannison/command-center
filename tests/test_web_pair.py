"""The /pair page: loopback Host only, a code is made by a CSRF-protected POST, never by a GET."""

import re

import pytest

from auth_rig import BASE_URL, AuthRig, make_auth_rig
from command_center.core.pairing import hash_token


@pytest.fixture
def rig() -> AuthRig:
    return make_auth_rig()


def minted_token(html: str) -> str:
    match = re.search(r'<code id="pair-token">([^<]+)</code>', html)
    assert match is not None, "the fragment shows no token"
    return match.group(1)


def test_the_pair_page_has_a_button_and_makes_no_token(rig: AuthRig) -> None:
    response = rig.local.get("/pair")
    assert response.status_code == 200
    assert 'hx-post="/pair/code"' in response.text
    assert "<svg" not in response.text
    assert rig.store.pairing_hashes() == set()


def test_the_pair_page_is_linked_from_the_navigation(rig: AuthRig) -> None:
    assert 'href="/pair"' in rig.local.get("/").text


def test_a_get_never_makes_a_token(rig: AuthRig) -> None:
    rig.local.get("/pair")
    rig.local.get("/pair/code")
    assert rig.store.pairing_hashes() == set()


def test_making_a_code_without_the_csrf_header_is_403_and_makes_nothing(rig: AuthRig) -> None:
    response = rig.local.post("/pair/code")
    assert response.status_code == 403
    assert rig.store.pairing_hashes() == set()


def test_making_a_code_with_a_wrong_csrf_token_is_403(rig: AuthRig) -> None:
    response = rig.local.post("/pair/code", headers={"X-CSRF-Token": "fake-wrong-csrf"})
    assert response.status_code == 403
    assert rig.store.pairing_hashes() == set()


def test_a_code_shows_a_qr_the_url_and_the_token(rig: AuthRig) -> None:
    response = rig.local.post("/pair/code", headers=rig.csrf())
    assert response.status_code == 200
    token = minted_token(response.text)
    assert "<svg" in response.text
    assert BASE_URL in response.text
    assert rig.store.pairing_hashes() == {hash_token(token)}


def test_the_code_fragment_is_never_cached(rig: AuthRig) -> None:
    response = rig.local.post("/pair/code", headers=rig.csrf())
    assert response.headers["cache-control"] == "no-store"


def test_the_qr_is_the_json_payload_and_the_token_is_not_in_a_url(rig: AuthRig) -> None:
    html = rig.local.post("/pair/code", headers=rig.csrf()).text
    token = minted_token(html)
    assert f"?token={token}" not in html
    assert f"/{token}" not in html


def test_the_shown_token_pairs_a_phone_once(rig: AuthRig) -> None:
    token = minted_token(rig.local.post("/pair/code", headers=rig.csrf()).text)
    first = rig.remote.post("/v1/pair", json={"pairing_token": token, "device_name": "Pixel"})
    again = rig.remote.post("/v1/pair", json={"pairing_token": token, "device_name": "Pixel"})
    assert (first.status_code, again.status_code) == (200, 401)


def test_asking_for_a_second_code_cancels_the_first(rig: AuthRig) -> None:
    headers = rig.csrf()
    first = minted_token(rig.local.post("/pair/code", headers=headers).text)
    second = minted_token(rig.local.post("/pair/code", headers=headers).text)
    assert first != second
    assert rig.remote.post("/v1/pair", json={"pairing_token": first}).status_code == 401
    assert rig.remote.post("/v1/pair", json={"pairing_token": second}).status_code == 200


def test_the_page_states_the_expiry_and_that_the_code_works_once(rig: AuthRig) -> None:
    html = rig.local.post("/pair/code", headers=rig.csrf()).text
    assert "5 minutes" in html
    assert "once" in html


def test_without_a_tailnet_name_the_page_says_how_to_set_one_and_makes_no_token() -> None:
    rig = make_auth_rig(base_url=None, remote_hosts=())
    page = rig.local.get("/pair")
    assert "CC_ALLOWED_HOSTS" in page.text
    response = rig.local.post("/pair/code", headers=rig.csrf())
    assert "CC_ALLOWED_HOSTS" in response.text
    assert "<svg" not in response.text
    assert rig.store.pairing_hashes() == set()


def test_the_loopback_address_may_open_the_page(rig: AuthRig) -> None:
    from fastapi.testclient import TestClient  # noqa: PLC0415

    client = TestClient(rig.app, base_url="http://127.0.0.1:8765")
    assert client.get("/pair").status_code == 200


def test_the_tailnet_host_cannot_open_the_page_even_with_a_token(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    response = rig.remote.get("/pair", headers=rig.bearer(phone.access_token))
    assert response.status_code == 404


def test_the_tailnet_host_cannot_make_a_code_even_with_a_token(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    headers = {**rig.csrf(), **rig.bearer(phone.access_token)}
    assert rig.remote.post("/pair/code", headers=headers).status_code == 404
    assert rig.store.pairing_hashes() == set()


def test_a_loopback_host_behind_a_proxy_cannot_open_the_page_without_a_token(
    rig: AuthRig,
) -> None:
    assert rig.local.get("/pair", headers={"X-Forwarded-For": "100.64.0.9"}).status_code == 401


def test_a_loopback_host_behind_a_proxy_with_a_token_still_cannot_make_a_code(
    rig: AuthRig,
) -> None:
    phone = rig.pair_phone()
    headers = {
        **rig.csrf(),
        **rig.bearer(phone.access_token),
        "X-Forwarded-For": "100.64.0.9",
    }
    assert rig.local.post("/pair/code", headers=headers).status_code == 404
    assert rig.store.pairing_hashes() == set()
