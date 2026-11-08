"""Host-header classification: loopback, remote (allowed names) or rejected."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from command_center.core.hosts import (
    LOOPBACK_HOSTS,
    PROXY_HEADER_NAMES,
    Exposure,
    classify_request,
    host_name,
    is_proxy_header,
)

REMOTE = {"mac.tail.ts.net"}


def test_constants() -> None:
    assert frozenset({"localhost", "127.0.0.1"}) == LOOPBACK_HOSTS
    assert frozenset(
        {
            "forwarded",
            "x-forwarded-for",
            "x-forwarded-host",
            "x-forwarded-proto",
            "x-forwarded-port",
            "x-real-ip",
            "via",
        }
    ) == frozenset(PROXY_HEADER_NAMES)


# ---------------------------------------------------------------- is_proxy_header


@pytest.mark.parametrize(
    "name",
    [
        "Forwarded",
        "X-Forwarded-For",
        "x-forwarded-host",
        "X-FORWARDED-PROTO",
        "X-Forwarded-Port",
        "X-Real-IP",
        "Via",
        "Tailscale-User-Login",
        "tailscale-user-name",
        "TAILSCALE-HEADERS-INFO",
        "tailscale-",
    ],
)
def test_proxy_headers_are_recognised_case_insensitively(name: str) -> None:
    assert is_proxy_header(name)


@pytest.mark.parametrize(
    "name", ["Host", "Accept", "Authorization", "X-Forwarded", "Tailscale", "Xtailscale-a", ""]
)
def test_ordinary_headers_are_not_proxy_headers(name: str) -> None:
    assert not is_proxy_header(name)


# ---------------------------------------------------------------- host_name


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("localhost", "localhost"),
        ("LOCALHOST", "localhost"),
        ("localhost:8765", "localhost"),
        ("127.0.0.1:8765", "127.0.0.1"),
        ("Mac.Tail.TS.net.", "mac.tail.ts.net"),
        ("mac.tail.ts.net.:443", "mac.tail.ts.net"),
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("localhost:", ""),
        ("localhost:abc", ""),
        ("localhost:\u0663", ""),
        ("[::1]", ""),
        ("[::1]:8765", ""),
        ("::1", ""),
        ("a b", ""),
        ("local\thost", ""),
        ("evil.com/", ""),
        ("user@localhost", ""),
        ("localhost\\evil", ""),
        ("localhost?x", ""),
        ("localhost#x", ""),
        ("localhost\n", ""),
        ("\u212aeys.example", ""),
    ],
)
def test_host_name_examples(header: str | None, expected: str) -> None:
    assert host_name(header) == expected


def test_host_name_strips_only_one_trailing_dot() -> None:
    assert host_name("localhost..") == "localhost."


@given(st.one_of(st.none(), st.text()))
def test_host_name_never_raises_and_never_returns_dangerous_characters(
    header: str | None,
) -> None:
    name = host_name(header)
    assert not any(c in name for c in "/@\\?#[")
    assert not any(c.isspace() for c in name)
    assert name == name.lower()


# ---------------------------------------------------------------- classify_request


@pytest.mark.parametrize(
    ("host", "headers", "expected"),
    [
        ("localhost:8765", ["Host", "Accept"], Exposure.LOOPBACK),
        ("LOCALHOST", [], Exposure.LOOPBACK),
        ("127.0.0.1:8765", ["Host"], Exposure.LOOPBACK),
        ("localhost", ["X-Forwarded-For"], Exposure.REMOTE),
        ("localhost", ["Tailscale-User-Login"], Exposure.REMOTE),
        ("127.0.0.1", ["Host", "Via"], Exposure.REMOTE),
        ("localhost", ["host", "X-REAL-IP"], Exposure.REMOTE),
        ("mac.tail.ts.net", [], Exposure.REMOTE),
        ("Mac.Tail.TS.net:443", ["X-Forwarded-For"], Exposure.REMOTE),
        ("evil.com", [], Exposure.REJECTED),
        ("evil.com", ["X-Forwarded-For"], Exposure.REJECTED),
        ("localhost.evil.com", [], Exposure.REJECTED),
        ("127.0.0.1.evil.com", [], Exposure.REJECTED),
        (None, [], Exposure.REJECTED),
        ("", [], Exposure.REJECTED),
        ("[::1]", [], Exposure.REJECTED),
        ("[::1]:8765", [], Exposure.REJECTED),
    ],
)
def test_classify_request_matrix(host: str | None, headers: list[str], expected: Exposure) -> None:
    assert classify_request(host, headers, REMOTE) == expected


def test_classify_request_accepts_any_iterable_of_header_names() -> None:
    names = (n for n in ["Host", "X-Forwarded-For"])
    assert classify_request("localhost", names, REMOTE) == Exposure.REMOTE


def test_classify_request_compares_remote_hosts_in_lowercase() -> None:
    assert classify_request("mac.tail.ts.net", [], {"Mac.Tail.TS.net"}) == Exposure.REMOTE


def test_classify_request_with_no_remote_hosts_rejects_everything_not_loopback() -> None:
    assert classify_request("mac.tail.ts.net", [], frozenset()) == Exposure.REJECTED


def test_a_loopback_name_in_remote_hosts_does_not_change_the_loopback_rule() -> None:
    both = {"localhost", "mac.tail.ts.net"}
    assert classify_request("localhost", [], both) == Exposure.LOOPBACK
    assert classify_request("localhost", ["X-Forwarded-For"], both) == Exposure.REMOTE
    assert classify_request("localhost", ["X-Forwarded-For"], frozenset()) == Exposure.REMOTE


def test_an_empty_remote_host_entry_never_matches_a_missing_host() -> None:
    assert classify_request(None, [], {""}) == Exposure.REJECTED
    assert classify_request("[::1]", [], {""}) == Exposure.REJECTED


@given(
    st.one_of(st.none(), st.text()),
    st.lists(st.text(max_size=20), max_size=5),
    st.sets(st.text(max_size=20), max_size=5),
)
def test_classify_request_never_says_loopback_for_a_host_outside_the_loopback_set(
    host: str | None, headers: list[str], remotes: set[str]
) -> None:
    result = classify_request(host, headers, remotes)
    if host_name(host) not in LOOPBACK_HOSTS:
        assert result != Exposure.LOOPBACK
    if result == Exposure.LOOPBACK:
        assert not any(is_proxy_header(h) for h in headers)


@given(st.text(max_size=20), st.lists(st.text(max_size=20), max_size=5))
def test_classify_request_rejects_a_host_that_is_neither_loopback_nor_allowed(
    host: str, headers: list[str]
) -> None:
    name = host_name(host)
    if name not in LOOPBACK_HOSTS:
        assert classify_request(host, headers, frozenset()) == Exposure.REJECTED
