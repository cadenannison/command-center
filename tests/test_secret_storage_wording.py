"""Where credentials live is worded so it is true in both secret-store modes (decision 0192).

The OS keychain is the default; a container uses a protected file (decision 0073). Text a user reads
must not say the keychain is always the place.
"""

import re
from pathlib import Path

import pytest

from command_center.web.howto import AI_HOWTOS, HOWTO, HowTo
from settings_ux_support import card, make_ux_rig

ROOT = Path(__file__).resolve().parent.parent
ONLY_HERE = "stored only on this computer"
# "in the keychain", "in your keychain", "in the OS keychain": a claim that the keychain is where
# credentials always are. A mention that names the file alternative right after it ("in the OS
# keychain, or in a protected file", "in the OS keychain (or a file ...)") is true and allowed.
ALWAYS_KEYCHAIN = re.compile(
    r"\bin\s+(?:the|your)\s+(?:OS\s+)?keychain"
    r"(?!,?\s+or\s+(?:in\s+)?a\s+(?:protected\s+)?file|\s+\(or\s+a\s+file)",
    re.IGNORECASE,
)
USER_FACING_DOCS = (
    "README.md",
    "SECURITY.md",
    "docs/sources.md",
    "docs/first-run.md",
    "docs/runbook.md",
    "docs/contracts/storage.md",
)


def howto_text(how: HowTo) -> str:
    return " ".join((*how.steps, how.note))


def test_the_settings_page_says_values_are_stored_only_on_this_computer() -> None:
    html = make_ux_rig(("canvas",)).client.get("/settings").text

    assert ONLY_HERE in html
    assert "in the OS keychain, or in a protected file when running under Docker" in html


def test_the_settings_page_does_not_say_the_keychain_is_always_the_place() -> None:
    html = make_ux_rig(("canvas",)).client.get("/settings").text

    assert ALWAYS_KEYCHAIN.search(html) is None


@pytest.mark.parametrize("source", sorted(HOWTO))
def test_no_source_how_to_says_the_keychain_is_always_the_place(source: str) -> None:
    assert ALWAYS_KEYCHAIN.search(howto_text(HOWTO[source])) is None
    assert "keychain" not in howto_text(HOWTO[source]).lower()


def test_no_ai_how_to_names_the_keychain() -> None:
    assert [name for name, how in AI_HOWTOS if "keychain" in howto_text(how).lower()] == []


def test_the_chat_key_how_to_says_where_the_key_is_kept() -> None:
    assert "kept only on this computer" in howto_text(HOWTO["chat"])


def test_the_chat_card_on_the_page_carries_that_line() -> None:
    html = make_ux_rig(("chat",)).client.get("/settings").text

    assert "kept only on this computer" in card(html, "chat")


@pytest.mark.parametrize("path", USER_FACING_DOCS)
def test_user_facing_docs_do_not_say_the_keychain_is_always_the_place(path: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")

    assert ALWAYS_KEYCHAIN.findall(text) == []
