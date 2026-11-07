"""Request-scoped access to the wired services."""

from typing import Annotated

from fastapi import Depends, Request

from command_center.services.container import Container


def get_container(request: Request) -> Container:
    """Return the container the app was created with (built at startup when given a factory)."""
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:
        msg = "The service container is not ready; the app has not started"
        raise RuntimeError(msg)
    return container


ContainerDep = Annotated[Container, Depends(get_container)]
