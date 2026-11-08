"""CSRF: every non-GET in web/ needs the per-process token; reads do not."""

import asyncio
import re
from collections.abc import Mapping

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from command_center.core.schema import ValidationResult
from command_center.web import create_router
from fake_adapter import FakeAdapter
from web_rig import CSRF, LOCAL, WebRig, make_rig

CREDS = {"token": "fake-canvas-token-ABCD1234"}
WRITES = [("PUT", "/settings/canvas"), ("DELETE", "/settings/canvas")]


@pytest.fixture
def rig() -> WebRig:
    return make_rig()


def token_in(html: str) -> str:
    match = re.search(r'hx-headers=\'\{"X-CSRF-Token": "([^"]+)"\}\'', html)
    assert match is not None
    return match.group(1)


@pytest.mark.parametrize(("method", "path"), WRITES)
def test_a_write_without_the_token_is_403_and_changes_nothing(
    rig: WebRig, method: str, path: str
) -> None:
    rig.client.put("/settings/canvas", data=CREDS, headers=rig.headers)
    before = rig.secrets.get("canvas")

    response = rig.client.request(method, path, data={"token": "fake-other-token-99999999"})

    assert response.status_code == 403
    assert rig.secrets.get("canvas") == before
    assert len(rig.adapters["canvas"].validations) == 1


@pytest.mark.parametrize(("method", "path"), WRITES)
def test_a_write_with_the_wrong_token_is_403(rig: WebRig, method: str, path: str) -> None:
    response = rig.client.request(method, path, headers={"X-CSRF-Token": CSRF + "x"})

    assert response.status_code == 403


@pytest.mark.parametrize(("method", "path"), WRITES)
def test_a_token_in_a_form_field_or_query_is_not_accepted(
    rig: WebRig, method: str, path: str
) -> None:
    response = rig.client.request(method, f"{path}?csrf_token={CSRF}", data={"csrf_token": CSRF})

    assert response.status_code == 403


def test_a_write_with_the_token_goes_through(rig: WebRig) -> None:
    response = rig.client.put("/settings/canvas", data=CREDS, headers=rig.headers)

    assert response.status_code == 200
    assert rig.secrets.get("canvas") == CREDS


def test_the_403_does_not_echo_the_token_or_the_submitted_values(rig: WebRig) -> None:
    response = rig.client.put("/settings/canvas", data=CREDS, headers={"X-CSRF-Token": "wrong"})

    assert CSRF not in response.text
    assert CREDS["token"] not in response.text


def test_the_token_check_comes_before_the_source_lookup(rig: WebRig) -> None:
    assert rig.client.put("/settings/nope").status_code == 403


@pytest.mark.parametrize("path", ["/", "/week", "/month", "/settings", "/settings/canvas/status"])
def test_reads_need_no_token(rig: WebRig, path: str) -> None:
    assert rig.client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/", "/week", "/month", "/settings"])
def test_every_page_hands_the_token_to_htmx(rig: WebRig, path: str) -> None:
    assert token_in(rig.client.get(path).text) == CSRF


def test_the_token_a_page_carries_is_the_one_that_works() -> None:
    rig = make_rig()
    app = FastAPI()
    app.include_router(create_router(rig.container))
    client = TestClient(app, base_url=LOCAL)

    token = token_in(client.get("/settings").text)

    assert client.put("/settings/canvas", data=CREDS).status_code == 403
    assert (
        client.put("/settings/canvas", data=CREDS, headers={"X-CSRF-Token": token}).status_code
        == 200
    )


def test_each_router_gets_its_own_unguessable_token() -> None:
    rig = make_rig()
    tokens: list[str] = []
    clients: list[TestClient] = []
    for _ in range(2):
        app = FastAPI()
        app.include_router(create_router(rig.container))
        clients.append(TestClient(app, base_url=LOCAL))
        tokens.append(token_in(clients[-1].get("/settings").text))

    assert tokens[0] != tokens[1]
    assert all(len(t) >= 32 for t in tokens)
    assert (
        clients[1].put("/settings/canvas", headers={"X-CSRF-Token": tokens[0]}).status_code == 403
    )


class GatedAdapter(FakeAdapter):
    """A gmail adapter whose validate waits, like a Google sign-in a person has not finished."""

    def __init__(self) -> None:
        super().__init__("gmail")
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def validate(self, creds: Mapping[str, str]) -> ValidationResult:
        self.entered.set()
        await self.release.wait()
        return await super().validate(creds)


async def test_a_second_submit_while_one_is_in_flight_is_refused() -> None:
    gated = GatedAdapter()
    rig = make_rig(adapters={"gmail": gated})
    transport = httpx.ASGITransport(app=rig.app)
    async with httpx.AsyncClient(
        transport=transport, base_url=LOCAL, headers=rig.headers
    ) as client:
        first = asyncio.create_task(client.put("/settings/gmail", data={"client_json": "{}"}))
        await gated.entered.wait()

        second = await client.put("/settings/gmail", data={"client_json": "{}"})
        gated.release.set()
        done = await first

    assert "Already connecting" in second.text
    assert len(gated.validations) == 1
    assert "Syncing…" in done.text
