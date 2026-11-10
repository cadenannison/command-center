"""The AI card's Ollama how-to tells a user with Ollama on another computer what that needs."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from ledger_support import open_ledger_rig
from sink_support import open_engine
from web_chat_support import make_web_chat_rig


@pytest.fixture
def card(tmp_path: Path) -> Iterator[str]:
    for engine in open_engine("sqlite", tmp_path):
        yield make_web_chat_rig(open_ledger_rig(engine)).page("/settings")


def test_the_ollama_how_to_names_the_setting_that_makes_it_reachable(card: str) -> None:
    assert "OLLAMA_HOST=0.0.0.0:11434" in card


def test_the_ollama_how_to_names_the_firewall_port(card: str) -> None:
    assert "allow port 11434 through its firewall" in card


def test_the_ollama_how_to_warns_that_plain_http_is_open_to_the_network(card: str) -> None:
    assert "anyone on that network can reach the server" in card


def test_no_how_to_tells_the_user_to_put_a_key_in_the_address(card: str) -> None:
    assert "Keep the address free of keys" in card


def test_the_ollama_how_to_says_it_listens_on_this_computer_only_by_default(card: str) -> None:
    assert "listens only on 127.0.0.1 (this computer) by default" in card


def test_the_ollama_how_to_says_another_machine_needs_the_setting_made_there(card: str) -> None:
    assert "another computer needs OLLAMA_HOST set on that computer" in card


def test_the_ollama_how_to_says_the_agenda_text_crosses_a_lan_unencrypted(card: str) -> None:
    assert "your agenda text crosses the network unencrypted" in card
