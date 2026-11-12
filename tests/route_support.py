"""Enumerate every endpoint of a FastAPI app, through the nested routers FastAPI 0.16x builds."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from starlette.routing import Mount

SAMPLE = {
    "period": "day",
    "source": "canvas",
    "device_id": "no-such-device",
    "item_id": "no-such-item",
    "conversation_id": "no-such-chat",
    "dashboard_id": "no-such-dashboard",
}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class Endpoint:
    method: str
    template: str

    @property
    def path(self) -> str:
        return self.template.format(**SAMPLE)


def walk(routes: Any, prefix: str = "") -> Iterator[Endpoint]:  # noqa: ANN401
    """Yield one Endpoint per (method, path template); fail on a node it does not understand."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:  # an included router: FastAPI nests these
            yield from walk(inner.routes, prefix + route.include_context.prefix)
            continue
        path = getattr(route, "path", None)
        if path is None:
            msg = f"a route of type {type(route).__name__} has no path; teach this walker about it"
            raise AssertionError(msg)
        methods = (
            {"GET"} if isinstance(route, Mount) else set(getattr(route, "methods", None) or ())
        )
        if not methods:
            msg = f"{type(route).__name__} {path} has no HTTP methods (a websocket?); classify it"
            raise AssertionError(msg)
        if "GET" in methods:
            methods.discard("HEAD")  # Starlette's own Route adds HEAD next to GET
        for method in sorted(methods):
            yield Endpoint(method, prefix + path)
