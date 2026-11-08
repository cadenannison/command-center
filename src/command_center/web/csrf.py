"""Per-process CSRF token. Every non-GET request must send it in the X-CSRF-Token header."""

import secrets
from collections.abc import Callable

from fastapi import HTTPException, Request

CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def new_token() -> str:
    """A fresh unguessable token; one is made per process, not per session."""
    return secrets.token_urlsafe(32)


def require_csrf(token: str) -> Callable[[Request], None]:
    """Build a dependency that answers 403 to a non-GET request without the right token."""

    def check(request: Request) -> None:
        if request.method in _SAFE_METHODS:
            return
        supplied = request.headers.get(CSRF_HEADER, "")
        if not secrets.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(status_code=403, detail="CSRF token missing or wrong")

    return check
