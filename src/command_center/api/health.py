"""Liveness endpoint."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/health", summary="Liveness check")
def health() -> dict[str, str]:
    """Report that the server is up."""
    return {"status": "ok"}
