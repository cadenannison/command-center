"""Settings routes. Credentials go in through PUT and never come back out."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from command_center.api.deps import ContainerDep
from command_center.api.errors import INVALID_REQUEST, NOT_FOUND
from command_center.services.models import ConnectResult, SourceSettings

router = APIRouter(prefix="/v1", tags=["settings"])

CredentialKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
CredentialValue = Annotated[str, StringConstraints(min_length=1, max_length=8192)]


class ConnectRequest(BaseModel):
    """Credentials for one source. Write-only: no response model has a field for them."""

    model_config = ConfigDict(extra="forbid")

    credentials: dict[CredentialKey, CredentialValue] = Field(
        min_length=1,
        max_length=32,
        repr=False,  # keeps the values out of any repr or log line made from the model
    )


@router.get("/settings", summary="Status of every source")
async def get_settings(container: ContainerDep) -> list[SourceSettings]:
    """Per source and per key: whether it is set and its last 4 characters; plus the sync state."""
    return await container.settings.status()


@router.put(
    "/settings/{source}",
    summary="Connect a source",
    responses={**NOT_FOUND, **INVALID_REQUEST},
)
async def put_settings(
    source: str,
    body: ConnectRequest,
    container: ContainerDep,
    background: BackgroundTasks,
) -> ConnectResult:
    """Validate and store the credentials; the sync runs after the response (state "syncing").

    A credential-only integration (the Gemini key) has no sync: its result carries `sync` null.
    """
    result = await container.settings.connect(source, body.credentials)
    if result.ok and result.sync is not None:
        background.add_task(container.sync.sync, source)
    return result


@router.delete(
    "/settings/{source}",
    summary="Disconnect a source",
    responses={**NOT_FOUND, **INVALID_REQUEST},
)
async def delete_settings(source: str, container: ContainerDep) -> SourceSettings:
    """Delete every stored key and every stored event of the source."""
    return await container.settings.disconnect(source)
