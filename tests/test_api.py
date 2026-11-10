"""The /v1 API through a real FastAPI app over fake adapters and in-memory stores."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from builders import NOW, make_event
from command_center.api import create_app
from command_center.core.errors import FatalError
from command_center.core.schema import Event
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from fake_adapter import KEYCHAIN_DETAIL, FakeAdapter, RecordingSleep, UnavailableSecretStore
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore

CRED = "fake-canvas-token-ABCD1234"
LOCAL = "http://localhost"
GET_PATHS = [
    "/v1/health",
    "/v1/settings",
    "/v1/attention",
    "/v1/events?from=2026-11-01T00:00:00Z&to=2026-12-01T00:00:00Z",
    "/v1/agenda/day?date=2026-11-07",
    "/v1/agenda/week?date=2026-11-07",
    "/v1/agenda/month?date=2026-11-07",
    "/openapi.json",
]


@dataclass
class Rig:
    client: TestClient
    adapter: FakeAdapter
    secrets: InMemorySecretStore
    events: InMemoryEventStore


def make_container(
    adapter: FakeAdapter,
    secrets: InMemorySecretStore | None = None,
) -> tuple[Container, InMemorySecretStore, InMemoryEventStore]:
    secrets = secrets if secrets is not None else InMemorySecretStore()
    events = InMemoryEventStore()
    clock = FakeClock(NOW)
    adapters = {adapter.name: adapter}
    sync = SyncService(adapters, secrets, events, clock, sleep=RecordingSleep())
    container = Container(
        sync=sync,
        agenda=AgendaService(events, clock, ZoneInfo("America/Denver")),
        settings=SettingsService(adapters, secrets, sync),
    )
    return container, secrets, events


@pytest.fixture
def rig() -> Rig:
    adapter = FakeAdapter(
        script=[
            [
                make_event(id="essay", kind="assignment", due=NOW + timedelta(hours=10)),
                make_event(id="meeting", start=NOW + timedelta(hours=1)),
            ]
        ]
    )
    container, secrets, events = make_container(adapter)
    return Rig(TestClient(create_app(container), base_url=LOCAL), adapter, secrets, events)


def seed(rig: Rig, *events: Event) -> None:
    rig.events.upsert(list(events))


def put_creds(rig: Rig, source: str = "canvas") -> Any:  # noqa: ANN401  (parsed JSON)
    return rig.client.put(f"/v1/settings/{source}", json={"credentials": {"token": CRED}})


def test_health_reports_ok(rig: Rig) -> None:
    assert rig.client.get("/v1/health").json() == {"status": "ok"}


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "localhost:8765", "127.0.0.1:8765"])
def test_loopback_host_headers_are_accepted(rig: Rig, host: str) -> None:
    assert rig.client.get("/v1/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "localhost.evil.example", "192.168.1.5", "[::1]"])
def test_other_host_headers_are_refused(rig: Rig, host: str) -> None:
    assert rig.client.get("/v1/health", headers={"Host": host}).status_code == 400


def test_events_in_a_window_come_back_ordered_and_scored(rig: Rig) -> None:
    seed(
        rig,
        make_event(id="b", kind="assignment", due=NOW + timedelta(hours=10), urgency=1),
        make_event(id="a", start=NOW + timedelta(hours=1)),
    )

    body = rig.client.get(
        "/v1/events", params={"from": "2026-11-07T00:00:00Z", "to": "2026-11-08T00:00:00Z"}
    ).json()

    assert [(e["id"], e["urgency"]) for e in body] == [("a", 60), ("b", 90)]


def test_a_reversed_window_has_the_same_422_shape_as_any_bad_request(rig: Rig) -> None:
    response = rig.client.get(
        "/v1/events", params={"from": "2026-11-08T00:00:00Z", "to": "2026-11-07T00:00:00Z"}
    )

    assert response.json() == {
        "detail": [
            {"loc": ["query", "to"], "msg": "`to` must be after `from`", "type": "value_error"}
        ]
    }


def test_the_schema_documents_one_422_body_that_has_no_input_field() -> None:
    container, _, _ = make_container(FakeAdapter())
    spec = create_app(container).openapi()

    refs = {
        op["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
        for path in spec["paths"].values()
        for op in path.values()
        if "422" in op["responses"]
    }

    assert refs == {"#/components/schemas/ValidationErrorBody"}
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    assert "input" not in spec["components"]["schemas"]["ValidationIssue"]["properties"]


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-11-08T00:00:00Z", "to": "2026-11-07T00:00:00Z"},
        {"from": "2026-11-07T00:00:00Z", "to": "2026-11-07T00:00:00Z"},
        {"from": "2026-11-07T00:00:00", "to": "2026-11-08T00:00:00Z"},
        {"from": "yesterday", "to": "2026-11-08T00:00:00Z"},
        {"to": "2026-11-08T00:00:00Z"},
    ],
)
def test_events_rejects_a_bad_window(rig: Rig, params: dict[str, str]) -> None:
    assert rig.client.get("/v1/events", params=params).status_code == 422


@pytest.mark.parametrize(
    ("period", "expected"),
    [("day", ["today"]), ("week", ["today", "friday"]), ("month", ["today", "friday", "monday"])],
)
def test_agenda_returns_the_period_containing_the_date(
    rig: Rig, period: str, expected: list[str]
) -> None:
    seed(
        rig,
        make_event(id="today", start=NOW),
        make_event(id="friday", start=NOW + timedelta(days=1)),
        make_event(id="monday", start=NOW + timedelta(days=2)),
        make_event(id="december", start=NOW + timedelta(days=40)),
    )

    body = rig.client.get(f"/v1/agenda/{period}", params={"date": "2026-11-07"}).json()

    assert [e["id"] for e in body] == expected


def test_agenda_rejects_an_unknown_period_and_a_missing_or_bad_date(rig: Rig) -> None:
    assert rig.client.get("/v1/agenda/year", params={"date": "2026-11-07"}).status_code == 422
    assert rig.client.get("/v1/agenda/day").status_code == 422
    assert rig.client.get("/v1/agenda/day", params={"date": "soon"}).status_code == 422


def test_attention_lists_urgent_items_most_urgent_first(rig: Rig) -> None:
    seed(
        rig,
        make_event(id="soon", kind="assignment", due=NOW + timedelta(hours=10)),
        make_event(id="late", kind="assignment", due=NOW - timedelta(hours=1)),
        make_event(id="calm", kind="assignment", due=NOW + timedelta(days=5)),
    )

    assert [e["id"] for e in rig.client.get("/v1/attention").json()] == ["late", "soon"]


def test_settings_lists_each_source_with_no_keys_before_connecting(rig: Rig) -> None:
    assert rig.client.get("/v1/settings").json() == [
        {"source": "canvas", "keys": {}, "sync": None, "values": {}}
    ]


def test_put_settings_validates_and_stores_then_answers_before_the_sync_result(rig: Rig) -> None:
    body = put_creds(rig).json()

    assert (body["ok"], body["message"]) == (True, "Connected")
    assert body["sync"]["status"] == "syncing"
    assert dict(rig.secrets.get("canvas")) == {"token": CRED}


def test_put_settings_runs_the_sync_as_a_background_task(rig: Rig) -> None:
    put_creds(rig)  # the test client finishes background tasks before it returns

    (source,) = rig.client.get("/v1/settings").json()

    assert len(rig.adapter.fetches) == 1
    assert source["sync"]["status"] == "ok"
    assert {e.id for e in rig.events.query(_everything())} == {"essay", "meeting"}


def test_a_rejected_put_starts_no_background_sync() -> None:
    adapter = FakeAdapter(validate_error=FatalError("unsupported base url"))
    container, _, _ = make_container(adapter)
    client = TestClient(create_app(container), base_url=LOCAL)

    client.put("/v1/settings/canvas", json={"credentials": {"token": CRED}})

    assert adapter.fetches == []
    assert client.get("/v1/settings").json()[0]["sync"] is None


def test_get_settings_after_put_shows_status_only(rig: Rig) -> None:
    put_creds(rig)

    (source,) = rig.client.get("/v1/settings").json()

    assert source["keys"] == {"token": {"set": True, "last4": "1234"}}
    assert source["sync"]["status"] == "ok"


def test_put_with_rejected_credentials_stores_nothing() -> None:
    container, secrets, _ = make_container(
        FakeAdapter(validate_error=FatalError("unsupported base url"))
    )
    client = TestClient(create_app(container), base_url=LOCAL)

    response = client.put("/v1/settings/canvas", json={"credentials": {"token": CRED}})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert secrets.get("canvas") == {}


def test_a_failing_secret_store_shows_no_details_and_no_500(
    caplog: pytest.LogCaptureFixture,
) -> None:
    container, _, _ = make_container(FakeAdapter(), UnavailableSecretStore())  # type: ignore[arg-type]
    client = TestClient(create_app(container), base_url=LOCAL)

    with caplog.at_level(logging.DEBUG):
        responses = [
            client.put("/v1/settings/canvas", json={"credentials": {"token": CRED}}),
            client.get("/v1/settings"),
            client.post("/v1/sync"),
            client.delete("/v1/settings/canvas"),
        ]

    assert [r.status_code for r in responses] == [200, 200, 200, 200]
    for response in responses:
        assert KEYCHAIN_DETAIL not in response.text
        assert CRED not in response.text
    assert "secret store unavailable" in responses[1].text
    assert KEYCHAIN_DETAIL not in caplog.text


def test_put_for_an_unknown_source_is_404(rig: Rig) -> None:
    response = put_creds(rig, "gmail")

    assert response.status_code == 404
    assert "gmail" in response.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"credentials": {}},
        {"credentials": {"token": ""}},
        {"credentials": {"bad key!": CRED}},
        {"credentials": {"token": 12345}},
        {"credentials": {"token": CRED}, "extra": CRED},
        {"credentials": [CRED]},
    ],
)
def test_put_with_a_malformed_body_is_422_and_never_echoes_the_input(
    rig: Rig, body: dict[str, Any]
) -> None:
    response = rig.client.put("/v1/settings/canvas", json=body)

    assert response.status_code == 422
    assert CRED not in response.text
    assert "12345" not in response.text
    assert rig.secrets.get("canvas") == {}


def test_delete_settings_removes_the_secret_and_the_sync_state(rig: Rig) -> None:
    put_creds(rig)

    response = rig.client.delete("/v1/settings/canvas")

    assert response.json() == {"source": "canvas", "keys": {}, "sync": None, "values": {}}
    assert rig.secrets.get("canvas") == {}


def test_delete_for_an_unknown_source_is_404(rig: Rig) -> None:
    assert rig.client.delete("/v1/settings/gmail").status_code == 404


def test_post_sync_syncs_every_source_and_returns_their_states(rig: Rig) -> None:
    rig.secrets.set("canvas", "token", CRED)

    body = rig.client.post("/v1/sync").json()

    assert [(s["source"], s["status"]) for s in body] == [("canvas", "ok")]


def test_post_sync_reports_a_source_that_needs_reconnecting_without_failing(rig: Rig) -> None:
    response = rig.client.post("/v1/sync")

    assert response.status_code == 200
    assert response.json()[0]["status"] == "reconnect"


def test_a_credential_put_never_appears_in_any_get_response_or_log(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        put_creds(rig)
        rig.client.post("/v1/sync")
        responses = [rig.client.get(path) for path in GET_PATHS]

    assert all(r.status_code == 200 for r in responses)
    assert all(CRED not in r.text for r in responses)
    assert CRED not in caplog.text


def test_a_failing_source_message_and_logs_do_not_expose_the_credential(
    caplog: pytest.LogCaptureFixture,
) -> None:
    container, _, _ = make_container(FakeAdapter(script=[FatalError("feed is malformed")]))
    client = TestClient(create_app(container), base_url=LOCAL)

    with caplog.at_level(logging.DEBUG):
        client.put("/v1/settings/canvas", json={"credentials": {"token": CRED}})
        texts = [client.get("/v1/settings").text, client.post("/v1/sync").text]

    assert all(CRED not in text for text in texts)
    assert CRED not in caplog.text


def test_no_response_schema_has_a_field_that_could_carry_a_credential() -> None:
    container, _, _ = make_container(FakeAdapter())
    schemas = create_app(container).openapi()["components"]["schemas"]
    response_models = {name: spec for name, spec in schemas.items() if name != "ConnectRequest"}

    names = {prop for spec in response_models.values() for prop in spec.get("properties", {})}

    assert names.isdisjoint({"credentials", "creds", "token", "password", "secret", "value"})


def test_a_container_factory_is_called_at_startup_not_at_construction() -> None:
    calls: list[int] = []
    container, _, _ = make_container(FakeAdapter())

    def factory() -> Container:
        calls.append(1)
        return container

    app = create_app(factory)
    assert calls == []
    with TestClient(app, base_url=LOCAL) as client:
        assert client.get("/v1/settings").status_code == 200
    assert calls == [1]


def test_a_route_that_needs_the_container_fails_loudly_before_startup() -> None:
    container, _, _ = make_container(FakeAdapter())
    factory: Callable[[], Container] = lambda: container  # noqa: E731
    client = TestClient(create_app(factory), base_url=LOCAL)

    with pytest.raises(RuntimeError, match="not ready"):
        client.get("/v1/settings")


def _everything() -> Any:  # noqa: ANN401
    from command_center.core.windows import TimeWindow  # noqa: PLC0415

    return TimeWindow(start=NOW - timedelta(days=400), end=NOW + timedelta(days=400))
