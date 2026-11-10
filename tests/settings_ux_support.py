"""A web rig whose SettingsService has the clock, plus helpers for the settings-usability tests."""

import re
from collections.abc import Sequence
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from builders import NOW
from command_center.services.agenda import AgendaService
from command_center.services.container import Container
from command_center.services.settings import SettingsService
from command_center.services.sync import SyncService
from command_center.web import create_router
from fake_adapter import FakeAdapter, RecordingSleep
from fakes import FakeClock, InMemoryEventStore, InMemorySecretStore
from web_rig import CSRF, LOCAL, WebRig

DENVER = ZoneInfo("America/Denver")


def make_ux_rig(
    sources: Sequence[str] = ("canvas",),
    *,
    adapters: dict[str, FakeAdapter] | None = None,
    secrets: InMemorySecretStore | None = None,
    integrations: dict[str, FakeAdapter] | None = None,
) -> WebRig:
    secrets = secrets or InMemorySecretStore()
    events = InMemoryEventStore()
    clock = FakeClock(NOW)
    registered = adapters or {name: FakeAdapter(name) for name in sources}
    sync = SyncService(registered, secrets, events, clock, sleep=RecordingSleep())
    container = Container(
        sync=sync,
        agenda=AgendaService(events, clock, DENVER),
        settings=SettingsService(registered, secrets, sync, integrations, clock=clock),
    )
    app = FastAPI()
    app.include_router(create_router(container, csrf_token=CSRF))
    return WebRig(
        TestClient(app, base_url=LOCAL), app, container, registered, secrets, events, clock
    )


def put(rig: WebRig, source: str, **fields: str) -> str:
    response = rig.client.put(f"/settings/{source}", data=fields, headers=rig.headers)
    assert response.status_code == 200
    return response.text


def card(html: str, source: str) -> str:
    match = re.search(
        rf'<section class="card" id="source-{source}".*?</section>', html, flags=re.DOTALL
    )
    assert match is not None, f"no card for {source}"
    return match.group(0)


def field_tag(html: str, source: str, key: str) -> str:
    match = re.search(rf'<(?:input|textarea) id="f-{source}-{key}"[^>]*>', html)
    assert match is not None, f"no field {key} on {source}"
    return match.group(0)
