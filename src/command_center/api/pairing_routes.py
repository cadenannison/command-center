"""Phone pairing and device management under /v1. Handlers parse, call the service, respond."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, Security
from pydantic import BaseModel, ConfigDict, Field

from command_center.api.auth import bearer_scheme
from command_center.api.deps import ContainerDep
from command_center.api.errors import INVALID_REQUEST, NOT_FOUND, ErrorBody
from command_center.core.pairing import Device, IssuedTokens
from command_center.services.errors import CredentialRejectedError, PairingLockedError
from command_center.services.pairing import PairingService

router = APIRouter(prefix="/v1", tags=["pairing"])
devices_router = APIRouter(prefix="/v1", tags=["devices"], dependencies=[Security(bearer_scheme)])

_NO_STORE = {"Cache-Control": "no-store"}


class PairRequest(BaseModel):
    """The one-time token shown on the Mac's pairing page, and a name for the phone."""

    model_config = ConfigDict(extra="forbid")

    pairing_token: str = Field(min_length=1, max_length=128)
    device_name: str | None = Field(default=None, max_length=100)


class RefreshRequest(BaseModel):
    """The device's current refresh credential."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """A device's credentials. The refresh credential is single use: store the new one."""

    device_id: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - the OAuth scheme name, not a secret
    access_token: str
    access_expires_at: datetime
    refresh_token: str


class DeviceInfo(BaseModel):
    """A paired phone. Carries no credential."""

    id: str
    name: str
    created_at: datetime
    last_seen_at: datetime


_REJECTED: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorBody, "description": "The token or credential is not valid"},
    404: {"model": ErrorBody, "description": "Pairing is not available"},
    429: {
        "model": ErrorBody,
        "description": "Five failures in a row; wait Retry-After seconds",
        "headers": {"Retry-After": {"schema": {"type": "integer"}}},
    },
}


def _pairing(container: ContainerDep) -> PairingService:
    if container.pairing is None:
        raise HTTPException(status_code=404, detail="Pairing is not available")
    return container.pairing


PairingDep = Annotated[PairingService, Depends(_pairing)]


def _tokens(issued: IssuedTokens, response: Response) -> TokenResponse:
    response.headers.update(_NO_STORE)
    return TokenResponse(
        device_id=issued.device_id,
        access_token=issued.access_token,
        access_expires_at=issued.access_expires_at,
        refresh_token=issued.refresh_token,
    )


def _device(device: Device) -> DeviceInfo:
    return DeviceInfo(
        id=device.id,
        name=device.name,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
    )


def _refusal(exc: CredentialRejectedError | PairingLockedError) -> HTTPException:
    if isinstance(exc, PairingLockedError):
        return HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds), **_NO_STORE},
        )
    return HTTPException(status_code=401, detail=str(exc), headers=_NO_STORE)


@router.post(
    "/pair",
    summary="Exchange a pairing token for device credentials",
    responses={**_REJECTED, **INVALID_REQUEST},
)
def pair(body: PairRequest, response: Response, service: PairingDep) -> TokenResponse:
    """Trade the one-time pairing token (single use, 5 minutes) for an access and refresh token."""
    try:
        return _tokens(service.pair(body.pairing_token, body.device_name), response)
    except (CredentialRejectedError, PairingLockedError) as exc:
        raise _refusal(exc) from None


@router.post(
    "/pair/refresh",
    summary="Rotate a device's refresh credential",
    responses={**_REJECTED, **INVALID_REQUEST},
)
def refresh(body: RefreshRequest, response: Response, service: PairingDep) -> TokenResponse:
    """Trade the refresh credential for a new pair. Reusing a spent one revokes the device."""
    try:
        return _tokens(service.refresh(body.refresh_token), response)
    except (CredentialRejectedError, PairingLockedError) as exc:
        raise _refusal(exc) from None


@devices_router.get("/devices", summary="List paired devices")
def list_devices(service: PairingDep) -> list[DeviceInfo]:
    """Every paired phone, oldest first."""
    return [_device(device) for device in service.devices()]


@devices_router.delete(
    "/devices/{device_id}",
    summary="Revoke a paired device",
    status_code=204,
    responses={**NOT_FOUND, **INVALID_REQUEST},
)
def revoke_device(device_id: str, service: PairingDep) -> Response:
    """Delete a device; its access and refresh tokens stop working at once."""
    if not service.revoke(device_id):
        raise HTTPException(status_code=404, detail="Unknown device")
    return Response(status_code=204)
