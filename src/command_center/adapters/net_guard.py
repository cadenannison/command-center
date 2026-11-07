"""DNS-time SSRF guard: a public-looking name must not resolve to a private address."""

import asyncio
import socket

from command_center.core.errors import TransientError
from command_center.core.urlcheck import require_https_public

DEFAULT_LOOKUP_TIMEOUT = 5.0


async def ensure_public_host(
    host: str,
    timeout: float = DEFAULT_LOOKUP_TIMEOUT,  # noqa: ASYNC109  (enforced here by wait_for)
) -> None:
    """Raise unless host resolves, within timeout seconds, only to public addresses.

    ValueError: the host did not resolve, resolved to nothing, or any address is not public.
    TransientError: the lookup timed out (a retry may succeed). Messages never echo the host or
    addresses. The lookup thread cannot be cancelled and may outlive the timeout. The name can
    still be re-resolved to a private address between this check and the connection (DNS
    rebinding); see docs/contracts/adapters.md.
    """
    # Failures are raised outside the except blocks: the resolver's and urlcheck's own errors may
    # quote the host, so they must be neither the __cause__ nor the __context__ of ours.
    infos = None
    timed_out = False
    try:
        infos = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, host, None), timeout=timeout
        )
    except TimeoutError:
        timed_out = True
    except OSError:
        infos = None
    if timed_out:
        msg = "host lookup timed out"
        raise TransientError(msg)
    if infos is None:
        msg = "Rejected host: could not be resolved"
        raise ValueError(msg)
    # sockaddr[0] is the address for both AF_INET and AF_INET6.
    addresses = sorted({str(info[4][0]) for info in infos})
    if not addresses:
        msg = "Rejected host: resolved to no address"
        raise ValueError(msg)
    if not all(_is_public(address) for address in addresses):
        msg = "Rejected host: resolves to a private, loopback, link-local or non-global address"
        raise ValueError(msg)


def _is_public(address: str) -> bool:
    literal = f"[{address}]" if ":" in address else address
    try:
        require_https_public(f"https://{literal}/")
    except ValueError:
        return False
    return True
