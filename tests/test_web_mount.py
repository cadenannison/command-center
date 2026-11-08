"""Mounting: the router finds the container the way the API does."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from command_center.web import create_router
from web_rig import LOCAL, make_rig


def test_router_without_a_container_uses_the_one_on_app_state() -> None:
    rig = make_rig()
    app = FastAPI()
    app.state.container = rig.container
    app.include_router(create_router())

    assert TestClient(app, base_url=LOCAL).get("/settings").status_code == 200


def test_router_without_any_container_says_the_app_has_not_started() -> None:
    app = FastAPI()
    app.include_router(create_router())

    client = TestClient(app, base_url=LOCAL, raise_server_exceptions=False)

    assert client.get("/").status_code == 500


def test_the_web_routes_stay_out_of_the_openapi_contract() -> None:
    rig = make_rig()

    assert rig.app.openapi()["paths"] == {}
