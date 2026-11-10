"""Shared plumbing of the two httpx chat providers: the URL guard at call time and error mapping.

Every failure becomes a core.errors.ChatProviderError / ChatRateLimited with a fixed message: never
the URL, the key, the prompt or the server's own body (a hostile or buggy server may echo any of
them). Redirects are never followed, so a server cannot bounce a request to a refused address.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx

from command_center.adapters.net_guard import ensure_public_host
from command_center.core.errors import ChatProviderError, ChatRateLimited, TransientError
from command_center.core.urlcheck import require_chat_base_url

# A local model on a laptop can take a while; a hung server must still end.
TIMEOUT_SECONDS = 120.0
LOOKUP_TIMEOUT_SECONDS = 5.0
_BUSY = frozenset({429, 503})
_REJECTED_KEY = frozenset({401, 403})
_NOT_FOUND = 404
_ERROR_STATUS = 400
_LOCAL_SUFFIXES = (".local", ".localhost")


async def checked_base_url(base_url: str) -> str:
    """The base URL without a trailing slash, or ChatProviderError if it may not be called.

    The literal rules are core's (`require_chat_base_url`). A public-looking name is then resolved
    and refused unless every address is public, so a name cannot point at the LAN or the cloud
    metadata address. A local name (`*.local`, a single-label LAN name) is resolved too, and is
    refused when any address is link-local, metadata, unspecified, multicast or not on this
    machine or LAN (loopback and private addresses are what it is for). The check and the
    connection resolve the name separately, so DNS rebinding is not closed
    (docs/contracts/adapters.md).
    """
    try:
        _ = require_chat_base_url(base_url)
    except ValueError:
        msg = "The chat server address is not allowed"
        raise ChatProviderError(msg) from None
    parts = urlsplit(base_url)
    host = (parts.hostname or "").rstrip(".").lower()
    if _is_local_name(host):
        await _require_local_addresses(host, parts.scheme)
    elif _is_public_looking_name(host):
        try:
            await ensure_public_host(host)
        except TransientError:
            msg = "The chat server address could not be looked up"
            raise ChatProviderError(msg) from None
        except ValueError:
            msg = "The chat server address is not allowed"
            raise ChatProviderError(msg) from None
    return base_url.rstrip("/")


def _is_local_name(host: str) -> bool:
    if not host or host == "localhost" or host.endswith(".localhost"):
        return False
    if "." in host and not host.endswith(".local"):
        return False
    try:
        _ = ipaddress.ip_address(host)
    except ValueError:
        return True
    return False


async def resolve_addresses(host: str) -> set[str]:
    """The addresses a name resolves to; empty when it does not resolve in time."""
    try:
        infos = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, host, None), timeout=LOOKUP_TIMEOUT_SECONDS
        )
    except (TimeoutError, OSError):
        return set()
    return {str(info[4][0]) for info in infos}


async def _require_local_addresses(host: str, scheme: str) -> None:
    """Refuse a local name that resolves to an address the URL guard would refuse as a literal."""
    refused = "The chat server address is not allowed"
    addresses = await resolve_addresses(host)
    if not addresses:
        msg = "The chat server address could not be looked up"
        raise ChatProviderError(msg)
    for address in addresses:
        literal = f"[{address}]" if ":" in address else address
        try:
            _ = require_chat_base_url(f"{scheme}://{literal}/")
        except ValueError:
            raise ChatProviderError(refused) from None


def _is_public_looking_name(host: str) -> bool:
    if not host or "." not in host or host.endswith(_LOCAL_SUFFIXES):
        return False
    try:
        _ = ipaddress.ip_address(host)
    except ValueError:
        return True
    return False


async def post_json(
    name: str, url: str, payload: Mapping[str, object], headers: Mapping[str, str]
) -> object:
    """POST payload as JSON and return the decoded body; every failure is a fixed-text error."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.post(url, json=payload, headers=dict(headers))
    except httpx.TimeoutException:
        msg = f"{name} timed out"
        raise ChatProviderError(msg) from None
    except httpx.HTTPError:
        msg = f"{name} is unreachable; is it running?"
        raise ChatProviderError(msg) from None
    _check_status(name, response.status_code)
    try:
        return response.json()
    except ValueError:
        raise malformed(name) from None


def _check_status(name: str, status: int) -> None:
    if status in _BUSY:
        msg = f"{name} is busy or rate limited"
        raise ChatRateLimited(msg)
    if status in _REJECTED_KEY:
        msg = f"{name} rejected the API key"
        raise ChatProviderError(msg)
    if status == _NOT_FOUND:
        msg = f"{name} does not have that model or endpoint"
        raise ChatProviderError(msg)
    if status >= _ERROR_STATUS:
        msg = f"{name} request failed ({status})"
        raise ChatProviderError(msg)


def malformed(name: str) -> ChatProviderError:
    """The error for a reply that is not the shape the provider documents."""
    return ChatProviderError(f"{name} returned a malformed reply")
