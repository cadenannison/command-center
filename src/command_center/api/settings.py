"""Settings routes. Credentials go in through PUT and never come back out."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from command_center.api.deps import ContainerDep, LoopbackDep
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
    # Store the credentials without checking them; for a connect that failed with a transient
    # error (`can_save_unverified`). Nothing is synced (decision 0101).
    unverified: bool = False


@router.get("/settings", summary="Status of every source")
async def get_settings(container: ContainerDep, loopback: LoopbackDep) -> list[SourceSettings]:
    """Per source and per key: whether it is set and its last 4 characters; plus the sync state.

    `values` (the stored non-secret values) is filled for a loopback request only; any other
    caller gets it empty (decision 0106).
    """
    return [_shown(item, loopback=loopback) for item in await container.settings.status()]


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
    """Validate and store the credentials; the sync starts after the response (state "syncing").

    In distributed mode the api runs no sync: it queues a job for the source's worker, and
    `GET /v1/settings` shows the state the normalizer records when the worker reports.

    A credential-only integration (the Gemini key) has no sync: its result carries `sync` null.

    With `unverified: true` the credentials are stored without validation and no sync follows;
    a source is then left in an `error` state whose message starts with `Saved unverified:`.
    A failed connect sets `can_save_unverified` only after a transient (network) error.
    """
    if body.unverified:
        return await container.settings.save_unverified(source, body.credentials)
    result = await container.settings.connect(source, body.credentials)
    if result.ok and result.sync is not None:
        background.add_task(container.sync.sync, source)
    return result


@router.delete(
    "/settings/{source}",
    summary="Disconnect a source",
    responses={**NOT_FOUND, **INVALID_REQUEST},
)
async def delete_settings(
    source: str, container: ContainerDep, loopback: LoopbackDep
) -> SourceSettings:
    """Delete every stored key, event and sync state of the source.

    Work already in flight for the source is cancelled first: whatever it reports afterwards is
    dropped. A failure is a 200 with an "error" `sync`: nothing was removed (the cancel failed), or
    the credentials are gone but some stored data is not ("incomplete"); disconnect again to finish.
    """
    return _shown(await container.settings.disconnect(source), loopback=loopback)


def _shown(item: SourceSettings, *, loopback: bool) -> SourceSettings:
    """item as the caller may see it: no plain values unless the request is loopback."""
    return item if loopback else item.model_copy(update={"values": {}})
