"""peer_is_trusted: exact addresses and CIDR ranges, failing closed on anything odd."""

import pytest

from command_center.core.hosts import peer_is_trusted


def test_an_exact_address_is_trusted() -> None:
    assert peer_is_trusted("172.18.0.1", ["172.18.0.1"])


def test_a_different_address_is_not_trusted() -> None:
    assert not peer_is_trusted("172.18.0.5", ["172.18.0.1"])


def test_a_cidr_range_covers_its_members_only() -> None:
    assert peer_is_trusted("172.18.0.5", ["172.18.0.0/16"])
    assert not peer_is_trusted("172.19.0.5", ["172.18.0.0/16"])


def test_ipv6_loopback_can_be_trusted() -> None:
    assert peer_is_trusted("::1", ["::1"])
    assert not peer_is_trusted("::2", ["::1"])


def test_an_ipv4_mapped_peer_matches_its_ipv4_entry() -> None:
    assert peer_is_trusted("::ffff:172.18.0.1", ["172.18.0.1"])
    assert not peer_is_trusted("::ffff:172.18.0.5", ["172.18.0.1"])


def test_the_two_families_never_match_each_other() -> None:
    assert not peer_is_trusted("127.0.0.1", ["::1"])
    assert not peer_is_trusted("::1", ["127.0.0.0/8"])


def test_an_empty_list_trusts_nobody() -> None:
    assert not peer_is_trusted("127.0.0.1", [])


def test_a_garbage_entry_is_skipped_not_fatal_and_not_a_wildcard() -> None:
    assert not peer_is_trusted("172.18.0.5", ["garbage", "*", "localhost", ""])
    assert peer_is_trusted("172.18.0.5", ["garbage", "172.18.0.5"])


@pytest.mark.parametrize(
    "peer", [None, "", " ", "testclient", "localhost", "172.18.0", "1.2.3.4.5"]
)
def test_a_garbage_or_missing_peer_is_not_trusted(peer: str | None) -> None:
    assert not peer_is_trusted(peer, ["0.0.0.0/0", "::/0", "172.18.0.5"])
