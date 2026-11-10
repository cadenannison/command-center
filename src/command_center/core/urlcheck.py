"""SSRF guard for user-supplied URLs. Literal-host checks only: core does no DNS.

`require_https_public` is https-only. `require_chat_base_url` is the one deliberate exception: a
chat provider may run on the user's own machine or LAN (Ollama, a local OpenAI-compatible server),
which has no certificate, so plain http is allowed there and only there. Everything that is not a
local host still has to pass `require_https_public`, and cloud-metadata and link-local addresses
are refused over any scheme (decision 0160).
"""

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
_CHAT_SCHEMES = ("http", "https")
_IPV6 = 6
_METADATA_NAMES = frozenset({"metadata.google.internal", "metadata"})
_METADATA_IPS = frozenset(
    {ipaddress.ip_address("100.100.100.200"), ipaddress.ip_address("fd00:ec2::254")}
)
_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)


def _split(url: str) -> tuple[SplitResult, str | None]:
    """Parse url for a guard: ValueError (never echoing the URL) when it is malformed."""
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
    return parts, host


def _require_no_userinfo(parts: SplitResult) -> None:
    if "@" in parts.netloc:
        msg = "Rejected URL: must not embed credentials"
        raise ValueError(msg)


def require_https_public(url: str) -> str:
    """Return url unchanged if it is https to a public host; raise ValueError otherwise."""
    parts, host = _split(url)
    if parts.scheme.lower() != "https" or not host:
        msg = "Rejected URL: must be an https URL with a host"
        raise ValueError(msg)
    _require_no_userinfo(parts)
    _require_public_host(host.rstrip(".").lower())
    return url


def require_chat_base_url(url: str) -> str:
    """Return url unchanged if it may be a chat provider's base URL; raise ValueError otherwise.

    A local host (localhost, a LAN name, loopback, RFC1918, unique-local) may use http or https;
    anything else must pass `require_https_public`. Link-local, unspecified and multicast
    addresses and the cloud-metadata names and IPs are refused over any scheme. Paths are
    allowed; a query string or fragment is not, because a key must never ride in a URL.
    """
    parts, host = _split(url)
    if parts.scheme.lower() not in _CHAT_SCHEMES or not host:
        msg = "Rejected URL: must be an http or https URL with a host"
        raise ValueError(msg)
    _require_no_userinfo(parts)
    if "?" in url or "#" in url:
        msg = "Rejected URL: must not carry a query string or fragment"
        raise ValueError(msg)
    name = host.rstrip(".").lower()
    if name in _METADATA_NAMES:
        msg = "Rejected URL: host is a cloud metadata address"
        raise ValueError(msg)
    if not _is_local_chat_host(name):
        require_https_public(url)
    return url


def _is_local_chat_host(host: str) -> bool:
    """True for a host that may be reached over plain http; raises for an always-refused one."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        _require_hostname_shape(host)
        return "." not in host or host.endswith((".localhost", ".local"))
    if address.version == _IPV6 and address.is_loopback:
        return True
    unwrapped = (
        _unwrap_embedded_ipv4(address) if isinstance(address, ipaddress.IPv6Address) else address
    )
    for candidate in (address, unwrapped):
        if (
            candidate.is_link_local
            or candidate.is_unspecified
            or candidate.is_multicast
            or candidate in _METADATA_IPS
        ):
            msg = "Rejected URL: host is a link-local, unspecified, multicast or metadata address"
            raise ValueError(msg)
    return any(
        unwrapped in network for network in _LOCAL_NETWORKS if network.version == unwrapped.version
    )


def _require_public_host(host: str) -> None:
    if host == "localhost" or host.endswith((".localhost", ".local")):
        msg = "Rejected URL: host is local"
        raise ValueError(msg)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        _require_hostname_shape(host)
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


def _require_hostname_shape(host: str) -> None:
    if not _HOSTNAME_CHARS.fullmatch(host):
        msg = "Rejected URL: host has characters beyond ASCII letters, digits, - and ."
        raise ValueError(msg)
    if _NUMERIC_LABEL.fullmatch(host.rsplit(".", 1)[-1]):
        msg = "Rejected URL: host is a non-standard numeric address"
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
