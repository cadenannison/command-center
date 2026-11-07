"""Composition root for the API process: wires concrete infrastructure."""

from fastapi import FastAPI

from command_center.api.health import router as health_router

LOCAL_HOST = "127.0.0.1"  # the server binds loopback only; remote access is Tailscale Serve
DEFAULT_PORT = 8765


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(title="Command Center", version="0.1.0")
    app.include_router(health_router)
    return app


def main() -> None:  # pragma: no cover - process entry point
    """Run the API on loopback."""
    import uvicorn  # noqa: PLC0415

    uvicorn.run(create_app(), host=LOCAL_HOST, port=DEFAULT_PORT)
