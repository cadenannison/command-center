"""ensure_public_host resolves with a stubbed getaddrinfo; no real DNS."""

import socket
import threading
from collections.abc import Callable

import pytest

from command_center.adapters.net_guard import ensure_public_host
from command_center.core.errors import TransientError

type AddrInfo = tuple[int, int, int, str, tuple[object, ...]]


def v4(address: str) -> AddrInfo:
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))


def v6(address: str) -> AddrInfo:
    return (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, 0, 0, 0))


def resolving_to(monkeypatch: pytest.MonkeyPatch, *infos: AddrInfo) -> Callable[[], list[str]]:
    seen: list[str] = []

    def fake(host: str, _port: object) -> list[AddrInfo]:
        seen.append(host)
        return list(infos)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return lambda: seen


async def test_public_ipv4_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    resolving_to(monkeypatch, v4("93.184.216.34"))
    await ensure_public_host("example.com")


async def test_public_ipv6_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    resolving_to(monkeypatch, v6("2606:2800:220:1:248:1893:25c8:1946"))
    await ensure_public_host("example.com")


async def test_host_is_passed_to_the_resolver_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = resolving_to(monkeypatch, v4("93.184.216.34"))
    await ensure_public_host("canvas.school.edu")
    assert seen() == ["canvas.school.edu"]


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0"],  # noqa: S104
)
async def test_non_public_ipv4_is_rejected(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    resolving_to(monkeypatch, v4(address))
    with pytest.raises(ValueError, match="non-global"):
        await ensure_public_host("example.com")


@pytest.mark.parametrize("address", ["::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "ff02::1"])
async def test_non_public_ipv6_is_rejected(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    resolving_to(monkeypatch, v6(address))
    with pytest.raises(ValueError, match="non-global"):
        await ensure_public_host("example.com")


async def test_one_private_address_among_public_ones_rejects_the_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolving_to(monkeypatch, v4("93.184.216.34"), v4("10.0.0.5"))
    with pytest.raises(ValueError, match="non-global"):
        await ensure_public_host("example.com")


async def test_scoped_link_local_ipv6_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    resolving_to(monkeypatch, v6("fe80::1%en0"))
    with pytest.raises(ValueError, match="non-global"):
        await ensure_public_host("example.com")


async def test_unresolvable_host_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_host: str, _port: object) -> list[AddrInfo]:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(ValueError, match="could not be resolved"):
        await ensure_public_host("example.com")


async def test_host_resolving_to_nothing_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    resolving_to(monkeypatch)
    with pytest.raises(ValueError, match="no address"):
        await ensure_public_host("example.com")


async def test_error_does_not_echo_host_or_address(monkeypatch: pytest.MonkeyPatch) -> None:
    resolving_to(monkeypatch, v4("10.9.8.7"))
    with pytest.raises(ValueError, match="Rejected host") as caught:
        await ensure_public_host("internal.secret-corp.example")
    assert "secret-corp" not in str(caught.value)
    assert "10.9.8.7" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


async def test_slow_lookup_raises_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def blocked(_host: str, _port: object) -> list[AddrInfo]:
        release.wait()
        return [v4("93.184.216.34")]

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    try:
        with pytest.raises(TransientError, match="host lookup timed out") as caught:
            await ensure_public_host("example.com", timeout=0.01)
    finally:
        # The lookup thread cannot be cancelled; let it finish so the loop can shut down.
        release.set()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


async def test_lookup_timeout_error_does_not_echo_host(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def blocked(_host: str, _port: object) -> list[AddrInfo]:
        release.wait()
        return []

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    try:
        with pytest.raises(TransientError) as caught:
            await ensure_public_host("internal.secret-corp.example", timeout=0.01)
    finally:
        release.set()
    assert "secret-corp" not in str(caught.value)


async def test_lookup_finishing_within_the_timeout_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolving_to(monkeypatch, v4("93.184.216.34"))
    await ensure_public_host("example.com", timeout=5.0)


async def test_literal_public_ip_needs_no_network() -> None:
    await ensure_public_host("93.184.216.34")


async def test_literal_loopback_ip_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-global"):
        await ensure_public_host("127.0.0.1")
