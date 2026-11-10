"""The settings pages are the Mac's own: a phone gets 404 from the page's check (decision 0211)."""

import pytest
from fastapi.testclient import TestClient

from web_rig import LOCAL, WebRig, make_rig

PAGES = ["/settings", "/settings/canvas/status"]
URL = "https://fake-school.example"
TAILNET = "https://mac.tail1234.ts.net"


@pytest.fixture
def rig() -> WebRig:
    found = make_rig(("canvas",))
    saved = found.client.put(
        "/settings/canvas",
        data={"base_url": URL, "token": "fake-canvas-token-ABCD1234"},
        headers=found.headers,
    )
    assert saved.status_code == 200
    return found


@pytest.mark.parametrize("path", PAGES)
def test_loopback_gets_the_settings_page(rig: WebRig, path: str) -> None:
    assert rig.client.get(path).status_code == 200


def test_loopback_settings_page_prefills_the_stored_non_secret_value(rig: WebRig) -> None:
    assert URL in rig.client.get("/settings").text


@pytest.mark.parametrize("path", PAGES)
def test_a_tailnet_host_gets_404_and_no_stored_value(rig: WebRig, path: str) -> None:
    response = TestClient(rig.app, base_url=TAILNET).get(path)

    assert response.status_code == 404
    assert URL not in response.text


@pytest.mark.parametrize("path", PAGES)
def test_a_loopback_host_with_a_proxy_header_gets_404_and_no_stored_value(
    rig: WebRig, path: str
) -> None:
    client = TestClient(rig.app, base_url=LOCAL, headers={"X-Forwarded-For": "100.64.0.9"})

    response = client.get(path)

    assert response.status_code == 404
    assert URL not in response.text


@pytest.mark.parametrize("header", ["Forwarded", "X-Real-IP", "Via", "Tailscale-User-Login"])
def test_any_proxy_header_on_a_loopback_host_gets_404(rig: WebRig, header: str) -> None:
    client = TestClient(rig.app, base_url=LOCAL, headers={header: "x"})

    assert client.get("/settings").status_code == 404
