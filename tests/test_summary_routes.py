"""GET /v1/summary on an app that mounts the router (create_app does not yet)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from builders import NOW, make_event
from command_center.api.errors import install_error_handlers
from command_center.api.summary_routes import SUMMARY_OFF, router
from command_center.core.errors import SummaryProviderError
from command_center.core.summary import DailySummary
from command_center.services.container import Container
from fakes import FakeSummaryProvider
from summary_support import GOOD, OLD, Rig


def client_for(container: Container) -> TestClient:
    app = FastAPI()
    app.state.container = container
    app.include_router(router)
    install_error_handlers(app)
    return TestClient(app, base_url="http://localhost")


def rig_with_event(outcome: DailySummary | Exception = GOOD) -> Rig:
    rig = Rig(provider=FakeSummaryProvider(outcome))
    rig.events.upsert([make_event(id="m", title="Team meeting", start=NOW)])
    return rig


def test_summaries_are_off_by_default() -> None:
    """A container built without a summary service (the default) has no route data: 404."""
    rig = rig_with_event()
    container = rig.container(None)
    assert container.summary is None
    response = client_for(container).get("/v1/summary?date=2026-11-07")
    assert response.status_code == 404
    assert response.json() == {"detail": SUMMARY_OFF}
    assert rig.provider.calls == 0


def test_returns_the_summary_with_provider_and_cached() -> None:
    rig = rig_with_event()
    client = client_for(rig.container(rig.service))
    first = client.get("/v1/summary?date=2026-11-07")
    assert first.status_code == 200
    assert first.json() == {"summary": GOOD.model_dump(), "provider": "fake", "cached": False}
    second = client.get("/v1/summary?date=2026-11-07")
    assert second.json()["cached"] is True
    assert rig.provider.calls == 1


def test_provider_failure_is_still_a_200_with_a_fallback() -> None:
    rig = rig_with_event(SummaryProviderError("down"))
    rig.store.put(NOW.date().replace(day=1), OLD)
    body = client_for(rig.container(rig.service)).get("/v1/summary?date=2026-11-07").json()
    assert (body["provider"], body["cached"], body["summary"]["headline"]) == (
        "stored",
        True,
        OLD.headline,
    )


def test_date_is_required_and_validated_without_echoing_input() -> None:
    client = client_for(rig_with_event().container(None))
    assert client.get("/v1/summary").status_code == 422
    bad = client.get("/v1/summary?date=not-a-date")
    assert bad.status_code == 422
    assert "not-a-date" not in bad.text
