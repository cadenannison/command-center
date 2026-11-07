"""SSRF guard for user-supplied URLs. Literal-host checks only: core does no DNS."""

import ipaddress
import re
from urllib.parse import SplitResult, urlsplit

_UNSAFE_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")
_HOSTNAME_CHARS = re.compile(r"[a-z0-9.-]+")
_EMBEDDING_PREFIXES = (
    bytes.fromhex("0064ff9b" + "00" * 8),  # NAT64 64:ff9b::/96
    bytes(12),  # IPv4-compatible ::/96
)
_NUMERIC_LABEL = re.compile(r"\d+|0x[0-9a-f]*", re.IGNORECASE)


def require_https_public(url: str) -> str:
    """Return url unchanged if it is https to a public host; raise ValueError otherwise."""
    if _UNSAFE_CHARS.search(url):
        msg = "Rejected URL: malformed (contains whitespace or control characters)"
        raise ValueError(msg)
    parts: SplitResult | None = None
    host: str | None = None
    try:
        parts = urlsplit(url)
        _ = parts.port
        host = parts.hostname
    except ValueError:
        parts = None
    if parts is None:
        # Raised outside the except block: the parser's error embeds the netloc, credentials
        # included, so it must be neither the __cause__ nor the __context__ of ours.
        msg = "Rejected URL: malformed (cannot be parsed)"
        raise ValueError(msg)
    if parts.scheme.lower() != "https" or not host:
        msg = "Rejected URL: must be an https URL with a host"
        raise ValueError(msg)
    if "@" in parts.netloc:
        msg = "Rejected URL: must not embed credentials (userinfo)"
        raise ValueError(msg)
    _require_public_host(host.rstrip(".").lower())
    return url


def _require_public_host(host: str) -> None:
    if host == "localhost" or host.endswith((".localhost", ".local")):
        msg = "Rejected URL: host is local"
        raise ValueError(msg)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not _HOSTNAME_CHARS.fullmatch(host):
            msg = "Rejected URL: host has characters beyond ASCII letters, digits, - and ."
            raise ValueError(msg) from None
        if _NUMERIC_LABEL.fullmatch(host.rsplit(".", 1)[-1]):
            msg = "Rejected URL: host is a non-standard numeric address"
            raise ValueError(msg) from None
        return
    if isinstance(address, ipaddress.IPv6Address):
        address = _unwrap_embedded_ipv4(address)
    # is_global also covers ranges the individual is_* flags miss, such as CGNAT and 6to4.
    if (
        not address.is_global
        or address.is_multicast
        or (isinstance(address, ipaddress.IPv6Address) and address.is_site_local)
    ):
        msg = "Rejected URL: host is a private, loopback, link-local or non-global address"
        raise ValueError(msg)


def _unwrap_embedded_ipv4(
    address: ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Return the IPv4 inside a mapped, NAT64 or IPv4-compatible address (is_global allows them)."""
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    packed = address.packed
    if packed[:12] in _EMBEDDING_PREFIXES:
        return ipaddress.IPv4Address(packed[12:])
    return address
