"""SystemTokenSource draws from the OS random source; only the shape can be asserted."""

import pytest

from command_center.adapters.system_tokens import SystemTokenSource
from command_center.core.pairing import is_plausible_token
from command_center.core.ports import TokenSource


def test_satisfies_the_token_source_port() -> None:
    source: TokenSource = SystemTokenSource()
    assert is_plausible_token(source.new_token(16))


@pytest.mark.parametrize(("num_bytes", "length"), [(16, 22), (32, 43)])
def test_token_length_matches_the_requested_entropy(num_bytes: int, length: int) -> None:
    assert len(SystemTokenSource().new_token(num_bytes)) == length


def test_tokens_do_not_repeat() -> None:
    source = SystemTokenSource()
    assert len({source.new_token(16) for _ in range(200)}) == 200


@pytest.mark.parametrize("num_bytes", [0, -1, 15])
def test_refuses_less_than_128_bits(num_bytes: int) -> None:
    with pytest.raises(ValueError, match="at least 16"):
        SystemTokenSource().new_token(num_bytes)
