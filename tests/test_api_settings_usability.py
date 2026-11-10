"""The /v1 settings API: plain values in status, can_save_unverified, and the unverified flag."""

from fastapi.testclient import TestClient

from command_center.api import create_app
from command_center.core.errors import AuthExpired, TransientError
from fake_adapter import FakeAdapter
from fakes import InMemorySecretStore
from test_api import make_container

TOKEN = "fake-canvas-token-ABCD1234"  # noqa: S105  (fake- test value)
URL = "https://fake-school.example"


def make_client(adapter: FakeAdapter) -> tuple[TestClient, InMemorySecretStore]:
    container, secrets, _ = make_container(adapter)
    return TestClient(create_app(container), base_url="http://localhost"), secrets


def put(client: TestClient, **extra: object) -> dict[str, object]:
    body = {"credentials": {"token": TOKEN, "base_url": URL}, **extra}
    return client.put("/v1/settings/canvas", json=body).json()


def test_settings_shows_the_plain_value_and_only_set_and_last4_of_a_secret() -> None:
    client, secrets = make_client(FakeAdapter())
    secrets.set("canvas", "token", TOKEN)
    secrets.set("canvas", "base_url", URL)

    (item,) = client.get("/v1/settings").json()

    assert item["values"] == {"base_url": URL}
    assert item["keys"]["token"] == {"set": True, "last4": "1234"}
    assert TOKEN not in str(item)


def test_a_transient_failure_says_it_can_be_saved_unverified() -> None:
    client, _ = make_client(FakeAdapter(validate_error=TransientError("offline")))

    result = put(client)

    assert (result["ok"], result["can_save_unverified"]) == (False, True)


def test_a_rejected_credential_cannot_be_saved_unverified() -> None:
    client, _ = make_client(FakeAdapter(validate_error=AuthExpired("no")))

    assert put(client)["can_save_unverified"] is False


def test_an_unverified_put_stores_without_validating_and_leaves_an_unverified_state() -> None:
    adapter = FakeAdapter(validate_error=TransientError("offline"))
    client, secrets = make_client(adapter)

    result = put(client, unverified=True)

    assert result["ok"] is True
    assert dict(secrets.get("canvas")) == {"token": TOKEN, "base_url": URL}
    assert (adapter.validations, adapter.fetches) == ([], [])
    (item,) = client.get("/v1/settings").json()
    assert item["sync"]["status"] == "error"
    assert item["sync"]["message"].startswith("Saved unverified:")


def test_a_failed_connect_leaves_the_stored_credentials_alone() -> None:
    client, secrets = make_client(FakeAdapter(validate_error=AuthExpired("no")))
    secrets.set("canvas", "token", TOKEN)
    secrets.set("canvas", "base_url", URL)

    put(client)
    client.put("/v1/settings/canvas", json={"credentials": {"token": "fake-bad-token-99999999"}})

    assert dict(secrets.get("canvas")) == {"token": TOKEN, "base_url": URL}


def test_the_openapi_schema_describes_the_new_fields() -> None:
    client, _ = make_client(FakeAdapter())

    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert "values" in schemas["SourceSettings"]["properties"]
    assert "can_save_unverified" in schemas["ConnectResult"]["properties"]
    assert "unverified" in schemas["ConnectRequest"]["properties"]
