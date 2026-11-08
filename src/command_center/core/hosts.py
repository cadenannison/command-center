"""Host-header classification: loopback, an allowed remote name, or rejected."""

import re
from collections.abc import Collection, Iterable
from enum import StrEnum

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})
PROXY_HEADER_NAMES = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-forwarded-port",
        "x-real-ip",
        "via",
    }
)
_TAILSCALE_PREFIX = "tailscale-"
_PLAIN_HOSTNAME = re.compile(r"[a-z0-9._-]+", re.ASCII)


class Exposure(StrEnum):
    """Where a request appears to come from."""

    LOOPBACK = "loopback"
    REMOTE = "remote"
    REJECTED = "rejected"


def is_proxy_header(name: str) -> bool:
    """True for headers a reverse proxy adds (case-insensitive), including Tailscale's."""
    lowered = name.lower()
    return lowered in PROXY_HEADER_NAMES or lowered.startswith(_TAILSCALE_PREFIX)


def host_name(header: str | None) -> str:
    """Return the lowercase hostname of a Host header, or "" if it is not a plain hostname.

    One trailing dot is dropped, and a `:port` only when the port is all ASCII digits. Anything
    else (whitespace, `/ @ \\ ? # [`, non-ASCII, a leftover colon) gives "" so it can never match.
    """
    # ASCII is checked before lowercasing: some non-ASCII letters lowercase to ASCII ones.
    if not header or not header.isascii():
        return ""
    name = header.lower()
    head, sep, port = name.rpartition(":")
    if sep and port.isdigit():
        name = head
    name = name.removesuffix(".")
    return name if _PLAIN_HOSTNAME.fullmatch(name) else ""


def classify_request(
    host_header: str | None, header_names: Iterable[str], remote_hosts: Collection[str]
) -> Exposure:
    """Classify a request by its Host header and header names.

    A loopback Host that arrives with any proxy header is REMOTE, not LOOPBACK: Tailscale Serve
    proxies to 127.0.0.1 and a tailnet peer can choose its own Host, so the Host alone does not
    prove the request is local. A name in remote_hosts is REMOTE; everything else is REJECTED.
    """
    name = host_name(host_header)
    if name in LOOPBACK_HOSTS:
        if any(is_proxy_header(h) for h in header_names):
            return Exposure.REMOTE
        return Exposure.LOOPBACK
    if name and name in {h.lower() for h in remote_hosts}:
        return Exposure.REMOTE
    return Exposure.REJECTED
