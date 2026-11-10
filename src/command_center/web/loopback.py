"""Whether a request is from the Mac's own browser: loopback Host and no proxy header."""

from fastapi import HTTPException, Request

from command_center.core.hosts import Exposure, classify_request


def is_loopback(request: Request) -> bool:
    """True only for a loopback Host with no proxy header (decision 0057); fails closed."""
    exposure = classify_request(request.headers.get("host"), request.headers.keys(), ())
    return exposure is Exposure.LOOPBACK


def require_loopback(request: Request) -> None:
    """Dependency: 404 unless the request is from the Mac's own browser.

    A phone gets the same answer as for a page that does not exist, so nothing on it is revealed.
    """
    if not is_loopback(request):
        raise HTTPException(status_code=404, detail="Not found")
