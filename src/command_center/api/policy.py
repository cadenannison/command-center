"""Pure request rules for `DeviceAuthMiddleware`: what a paired phone may call, and the JSON check.

No I/O. A phone is any non-loopback request (decision 0057, item 5; decision 0060). It may read
the routes in `REMOTE_READS` and may `POST /v1/sync`. Everything else is refused, so a route added
tomorrow, read or write, is denied for a phone until someone lists it here
(`tests/test_remote_policy.py` fails until it is classified; decision 0412).
The item writes (`POST /v1/items`, `PATCH`/`DELETE /v1/items/{id}`, the `done` and `notes`
routes; decision 0126) are therefore loopback-only: they are not in `REMOTE_WRITES`. So are the
chat routes (`POST /v1/chat`, `DELETE /v1/chat/{id}`; the context preview is a denied read).
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


# The only reads a phone may make (decision 0412). Default deny: a route not listed here is refused
# for a phone, so a route added tomorrow is not phone-readable until someone lists it and adds its
# row to `tests/test_remote_policy.py`. `{name}` stands for exactly one whole path segment.
REMOTE_READS = frozenset(
    {
        "/v1/tasks",
        "/v1/dashboards",
        "/v1/dashboards/{dashboard_id}",
        "/v1/display-settings",
        "/v1/agenda/{period}",
        "/v1/events",
        "/v1/attention",
        "/v1/summary",
        "/v1/needs-me",
    }
)

# Reads that stay named as denied, though the allowlist already refuses them: the Mac's own web UI
# uses them (decision 0180), or they show what would be sent to an AI provider (decision 0165).
# Kept because `tests/test_chat_remote_policy.py` imports it; checked first, so a bad edit of
# `REMOTE_READS` cannot open them.
REMOTE_DENIED_READS = frozenset({"/v1/geocode", "/v1/chat/context-preview"})

_READS_BY_SEGMENTS = tuple(tuple(entry.split("/")) for entry in sorted(REMOTE_READS))


def _is_param(segment: str) -> bool:
    return segment.startswith("{") and segment.endswith("}")


def _on_read_list(path: str) -> bool:
    """Whether the path matches a `REMOTE_READS` entry segment by segment, never by prefix.

    A trailing slash, an empty segment, a `.` or `..` segment, or an extra segment never matches.
    """
    parts = tuple(path.split("/"))
    for template in _READS_BY_SEGMENTS:
        if len(template) != len(parts):
            continue
        if all(
            (_is_param(want) and got not in {"", ".", ".."}) or want == got
            for want, got in zip(template, parts, strict=True)
        ):
            return True
    return False


def remote_may_call(method: str, path: str) -> bool:
    """Whether a paired phone may make this request. Default deny: only listed routes pass."""
    if path in REMOTE_DENIED_READS:
        return False
    if method in SAFE_METHODS:
        return _on_read_list(path)
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
