"""The full app (API + web) over fakes, with pairing wired and a tailnet host allowed."""

import re
from dataclasses import dataclass, replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from command_center.api import create_app
from command_center.core.pairing import IssuedTokens
from command_center.services.container import Container
from command_center.services.pairing import PairingService
from fakes import FakeClock
from pairing_support import FakeTokenSource, InMemoryDeviceStore
from web_rig import make_rig

REMOTE = "mac.tail1234.ts.net"
BASE_URL = f"https://{REMOTE}"


@dataclass
class AuthRig:
    app: FastAPI
    container: Container
    service: PairingService
    store: InMemoryDeviceStore
    clock: FakeClock
    local: TestClient  # Host: localhost, the web UI's own origin
    remote: TestClient  # Host: the tailnet name, as Tailscale Serve delivers it

    def pair_phone(self, name: str = "Pixel") -> IssuedTokens:
        """A paired phone, made through the service."""
        return self.service.pair(self.service.start_pairing().token, name)

    @staticmethod
    def bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def csrf(self) -> dict[str, str]:
        """The CSRF header the web page would send, read from the page like htmx does."""
        page = self.local.get("/settings").text
        match = re.search(r'"X-CSRF-Token": "([^"]+)"', page)
        assert match is not None, "the page carries no CSRF token"
        return {"X-CSRF-Token": match.group(1)}


def make_auth_rig(
    *, base_url: str | None = BASE_URL, remote_hosts: tuple[str, ...] = (REMOTE,)
) -> AuthRig:
    web = make_rig(("canvas",))
    store = InMemoryDeviceStore()
    service = PairingService(store, FakeTokenSource(), web.clock, base_url=base_url)
    container = replace(web.container, pairing=service)
    app = create_app(container, remote_hosts=remote_hosts)
    return AuthRig(
        app=app,
        container=container,
        service=service,
        store=store,
        clock=web.clock,
        local=TestClient(app, base_url="http://localhost"),
        remote=TestClient(app, base_url=BASE_URL),
    )
