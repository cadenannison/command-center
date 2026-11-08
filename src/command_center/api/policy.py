"""Pure request rules for `DeviceAuthMiddleware`: what a paired phone may call, and the JSON check.

No I/O. A phone is any non-loopback request (decision 0057, item 5; decision 0060). It may read
and may `POST /v1/sync`. Everything else is refused, so a route added tomorrow is denied for a
phone until someone lists it here (`tests/test_remote_policy.py` fails until it is classified).
"""

from http import HTTPStatus
from urllib.parse import urlsplit

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# The only write a phone may make. Exact method and exact path.
REMOTE_WRITES = frozenset({("POST", "/v1/sync")})

# The API; everything else is the web UI, whose HTMX forms have their own CSRF token.
JSON_ONLY_PREFIX = "/v1/"
# These two take a JSON body model and answer 422 to a form or text/plain body before a handler
# runs (decision 0060, item 5). They still refuse a typeless body and doubled Content-Type headers.
JSON_ONLY_EXEMPT = frozenset({"/v1/pair", "/v1/pair/refresh"})


def remote_may_call(method: str, path: str) -> bool:
    """Whether a paired phone may make this request. Default deny for anything but a read."""
    if method in SAFE_METHODS:
        return True
    return (method, path) in REMOTE_WRITES


def refusal_status(path: str) -> HTTPStatus:
    """The status for a refused phone: 403 on the API, 404 on the web UI's own routes.

    The web pages already answer a phone's `POST /pair/code` with 404 (they do not exist for it),
    and tests/test_web_pair.py holds that; the rest of the web writes follow it (decision 0060).
    """
    return HTTPStatus.FORBIDDEN if path.startswith(JSON_ONLY_PREFIX) else HTTPStatus.NOT_FOUND


def is_json_content_type(value: str) -> bool:
    """True for `application/json`, any case, with or without parameters such as a charset."""
    media_type = value.partition(";")[0].strip().lower()
    return media_type == "application/json"


def writes_under_v1(method: str, path: str) -> bool:
    """Whether this is a write to the API, which the content-type and cross-site rules cover."""
    return method not in SAFE_METHODS and path.startswith(JSON_ONLY_PREFIX)


def content_type_ok(method: str, path: str, headers: list[tuple[bytes, bytes]]) -> bool:
    """Whether the request body (if any) is declared as exactly one JSON content type.

    A request with no body and no Content-Type is fine: the phone's `POST /v1/sync` and the
    DELETEs send neither. A body with no Content-Type is refused, because FastAPI would parse it
    as JSON and a cross-site `fetch` with a typeless Blob sends exactly that. The pairing routes
    are lenient about one thing only: a declared non-JSON type reaches their model, which is 422.
    """
    if not writes_under_v1(method, path):
        return True
    types = [value for name, value in headers if name.lower() == b"content-type"]
    if len(types) > 1:
        return False
    if types:
        return path in JSON_ONLY_EXEMPT or is_json_content_type(types[0].decode("latin-1"))
    return not _has_body(headers)


def is_cross_site(method: str, path: str, headers: list[tuple[bytes, bytes]]) -> bool:
    """Whether a browser marked this API write as coming from another site.

    `Sec-Fetch-Site: cross-site`, or an `Origin` that is not the Host the request was sent to
    (`null` included), is refused: a page on another origin can send a bodiless `no-cors` POST
    that needs no preflight. The phone app and curl send neither header (decision 0060).
    """
    if not writes_under_v1(method, path):
        return False
    values: dict[bytes, str] = {}
    for name, value in headers:  # the first of a repeated header, as the Host rule reads it
        values.setdefault(name.lower(), value.decode("latin-1"))
    if values.get(b"sec-fetch-site", "").lower() == "cross-site":
        return True
    origin = values.get(b"origin")
    if origin is None:
        return False
    host = values.get(b"host", "").lower()
    return urlsplit(origin).netloc.lower() != host


def _has_body(headers: list[tuple[bytes, bytes]]) -> bool:
    for name, value in headers:
        lowered = name.lower()
        if lowered == b"transfer-encoding":
            return True
        if lowered == b"content-length" and value.strip() not in {b"", b"0"}:
            return True
    return False
