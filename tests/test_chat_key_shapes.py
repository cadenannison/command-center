"""A key pasted into the address or model field is refused, never stored and never shown again.

An address is tested with core.redact plus its own rules (decisions 0258, 0291). A model name has
its own rule (decisions 0270, 0290): a known key prefix, an email shape, a run of 32 or more
letters and digits or 24 or more hex digits, a `user:password` shape, or more than 200 characters.
Both are best effort, so a key of another shape still gets through, which the AI card's text
says: keys go on the key card. The invented keys are built from parts so no scanner sees a
real-looking literal.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from command_center.core.chat import (
    address_holds_api_key,
    looks_like_api_key,
    model_name_looks_like_api_key,
)
from command_center.services.chat_settings import ChatDefaults, ChatSettings, normalise_provider
from command_center.services.errors import ChatNotConfiguredError, InvalidChatSettingError
from fakes import InMemoryAppSettingStore
from ledger_support import LedgerRig, open_ledger_rig
from sink_support import open_engine
from web_chat_support import HEADERS, WebChatRig, ai_card, make_web_chat_rig

OPENAI_STYLE = "sk-" + "proj" + "-fake1234" * 5
GOOGLE_STYLE = "AI" + "za" + "fake1234" * 4 + "x"
PLAIN_RUN = "fake1" + "A9b8C7d6" * 4  # 37 letters and digits, no separator
GITHUB_STYLE = "ghp_" + "fake1234" * 4
KEYS = [
    OPENAI_STYLE,
    GOOGLE_STYLE,
    GITHUB_STYLE,
    PLAIN_RUN,
    "gsk_" + "fake1234" * 4,
    "xai-" + "fake1234" * 4,
]
# Too short for redact to change; the prefix alone decides.
SHORT_PREFIXED = ["sk-fake12", "AIzafake12", "ghp_fake12"]
MODELS = [
    "llama3.2",
    "gemini-2.5-flash",
    "qwen2.5-coder:7b",
    "mistralai/mistral-7b-instruct",
    "anthropic/claude-sonnet-4.5",
    "gpt-4o-2024-08-06",
]
# Real names that redact would change (32 or more characters in a run of letters, digits, - and _).
# They are still key-shaped as an address path segment (decision 0258) but are valid model names
# (decision 0270).
LONG_REAL_NAMES = [
    "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M",
    "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
    "NousResearch-Hermes-3-Llama-3-1-8B",
]
BEDROCK_ARN = (
    "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/"
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
)
HOSTED_MODELS = [
    BEDROCK_ARN,
    "claude-3-5-sonnet@20240620",
    "claude-3-5-sonnet-v2@20241022",
    "gemini-pro@001",
    "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "anthropic/claude-3.5-sonnet:beta",
    "gemini-2.5-flash",
    "llama3.1:8b-instruct-q4_K_M",
    "accounts/fireworks/models/llama-v3p1-70b-instruct",
]
# Built from parts so no scanner sees a key literal.
MODEL_KEYS = [
    OPENAI_STYLE,
    GOOGLE_STYLE,
    GITHUB_STYLE,
    "gh" + "o_" + "fake1234" * 2,
    "gh" + "u_" + "fake1234" * 2,
    "gh" + "s_" + "fake1234" * 2,
    "github_" + "pat_" + "fake1234" * 2,
    "AK" + "IA" + "FAKE1234" * 2,
    "xo" + "xb-" + "fake1234" * 2,
    "xo" + "xp-" + "fake1234",
    "a1b2c3d4e5" * 4,  # 40 hex-looking characters
    "f" * 40,
    PLAIN_RUN,
    "k" * 33,
    "a-b." * 51 + "c",  # 205 characters, no key shape: refused for its length
    "a" * 201,
    "fw" + "_3Zq8Hk2LmN5pR7sT9vW1xY3a",
    "sk" + "_live_" + "fake1234",
    "sk" + "_test_" + "fake1234",
    "AS" + "IA" + "FAKE1234EXAMPLE",
    "0123456789abcdef01234567",  # 24 hex characters, the shortest refused run
    "ABCDEF0123456789abcdef0123456789-x",
    "bob" + "@" + "example.com",
    "bob" + "@" + "mail-server.example.com",
    "a.b+c" + "@" + "sub.example.org",
    "user" + ":" + "pw1234567890",
    "alice:Fake1234Pass",
]


@pytest.mark.parametrize("text", [*KEYS, *SHORT_PREFIXED, *LONG_REAL_NAMES])
def test_a_key_shaped_text_is_recognised(text: str) -> None:
    assert looks_like_api_key(text)


@pytest.mark.parametrize("text", [*MODELS, "", "v1", "openai", "api", "localhost:11434"])
def test_a_model_name_or_path_part_is_not_taken_for_a_key(text: str) -> None:
    assert not looks_like_api_key(text)


@pytest.mark.parametrize("name", MODEL_KEYS)
def test_a_key_shaped_model_name_is_recognised(name: str) -> None:
    assert model_name_looks_like_api_key(name)
    assert model_name_looks_like_api_key(f"  {name}  ")


@pytest.mark.parametrize("name", [*HOSTED_MODELS, *LONG_REAL_NAMES, *MODELS, "gpt-4o", "m", ""])
def test_a_real_model_name_is_not_taken_for_a_key(name: str) -> None:
    assert not model_name_looks_like_api_key(name)


def test_a_model_name_run_of_31_is_accepted_and_32_is_refused() -> None:
    assert not model_name_looks_like_api_key("x" * 31)
    assert model_name_looks_like_api_key("x" * 32)
    assert not model_name_looks_like_api_key("x" * 31 + "-" + "y" * 31)


def test_a_model_name_of_200_characters_is_accepted_and_201_is_not() -> None:
    name = "ab-" * 66 + "cd"  # 200 characters, runs of 2

    assert len(name) == 200
    assert not model_name_looks_like_api_key(name)
    assert model_name_looks_like_api_key(name + "d")


def test_a_key_prefix_decides_even_for_a_short_model_name() -> None:
    assert model_name_looks_like_api_key("sk-x")
    assert not model_name_looks_like_api_key("task-x")
    assert not model_name_looks_like_api_key("xoxo-x")


def test_an_address_with_a_numeric_host_and_port_is_accepted() -> None:
    """redact masks an IPv4 address, so only the path of an address is tested, never the host."""
    address = normalise_provider("ollama", "http://10.1.2.3:11434", "m")[1]

    assert address == "http://10.1.2.3:11434"


def test_an_address_whose_host_starts_with_a_key_prefix_is_accepted() -> None:
    address = normalise_provider("openai_compatible", "https://sk-llm-gateway.example.com/v1", "m")[
        1
    ]

    assert address == "https://sk-llm-gateway.example.com/v1"


def test_surrounding_spaces_do_not_hide_a_key() -> None:
    assert looks_like_api_key(f"  {OPENAI_STYLE}  ")


# --- the settings service ---------------------------------------------------------------------


@pytest.mark.parametrize("key", KEYS)
def test_a_key_as_the_model_name_is_refused_without_echoing_it(key: str) -> None:
    with pytest.raises(InvalidChatSettingError) as raised:
        _ = normalise_provider("ollama", "http://localhost:11434", key)

    assert key not in str(raised.value)
    assert "API key" in str(raised.value)


@pytest.mark.parametrize("model", [*MODELS, *HOSTED_MODELS, *LONG_REAL_NAMES])
def test_a_real_model_name_is_accepted(model: str) -> None:
    assert normalise_provider("ollama", None, model)[2] == model


@pytest.mark.parametrize("name", MODEL_KEYS)
def test_a_key_shaped_model_is_refused_by_the_service_without_echoing_it(name: str) -> None:
    with pytest.raises(InvalidChatSettingError) as raised:
        _ = normalise_provider("openai_compatible", "https://api.example.com/v1", name)

    assert name not in str(raised.value)


@pytest.mark.parametrize("name", [*SHORT_PREFIXED, GITHUB_STYLE])
def test_a_prefixed_value_is_refused_as_the_model_without_echoing_it(name: str) -> None:
    with pytest.raises(InvalidChatSettingError) as raised:
        _ = normalise_provider("ollama", None, name)

    assert name not in str(raised.value)
    assert "API key" in str(raised.value)


def test_a_model_name_over_the_length_limit_is_refused_without_echoing_it() -> None:
    name = "a-b." * 51  # 204 characters, no key shape

    with pytest.raises(InvalidChatSettingError) as raised:
        _ = normalise_provider("ollama", None, name)

    assert name not in str(raised.value)
    assert "200" in str(raised.value)


@pytest.mark.parametrize("key", KEYS)
def test_a_key_in_the_path_of_the_address_is_refused_without_echoing_it(key: str) -> None:
    with pytest.raises(InvalidChatSettingError) as raised:
        _ = normalise_provider("openai_compatible", f"https://api.example.com/v1/{key}", "m")

    assert key not in str(raised.value)
    assert "API key" in str(raised.value)


def test_an_ordinary_path_is_accepted() -> None:
    address = normalise_provider("openai_compatible", "https://api.example.com/openai/v1", "m")[1]

    assert address == "https://api.example.com/openai/v1"


async def test_a_refused_key_shaped_model_stores_nothing() -> None:
    store = InMemoryAppSettingStore()
    settings = ChatSettings(store, ChatDefaults())

    with pytest.raises(InvalidChatSettingError):
        await settings.set_provider("ollama", "http://localhost:11434", OPENAI_STYLE)

    assert store.get("chat.model") is None
    assert store.get("chat.kind") is None


async def test_a_key_shaped_model_stored_before_this_check_is_not_used() -> None:
    store = InMemoryAppSettingStore()
    store.set("chat.kind", "ollama")
    store.set("chat.base_url", "")
    store.set("chat.model", OPENAI_STYLE)

    with pytest.raises(ChatNotConfiguredError) as raised:
        _ = await ChatSettings(store, ChatDefaults()).config()

    assert OPENAI_STYLE not in str(raised.value)


# --- the card ---------------------------------------------------------------------------------


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[LedgerRig]:
    for engine in open_engine("sqlite", tmp_path):
        yield open_ledger_rig(engine)


@pytest.fixture
def rig(ledger: LedgerRig) -> WebChatRig:
    return make_web_chat_rig(ledger, enabled=False)


def save(rig: WebChatRig, **fields: str) -> str:
    response = rig.client.put("/ai/settings", data=fields, headers=HEADERS)
    assert response.status_code == 200
    return ai_card(response.text)


def field_value(html: str, field_id: str) -> str | None:
    match = re.search(rf'<input id="{field_id}"[^>]*?(?: value="([^"]*)")?>', html)
    assert match is not None
    return match.group(1)


@pytest.mark.parametrize("key", KEYS)
def test_a_key_pasted_into_the_address_is_not_shown_again(rig: WebChatRig, key: str) -> None:
    html = save(rig, kind="ollama", base_url=key, model="m")

    assert key not in html
    assert field_value(html, "ai-base-url") is None


@pytest.mark.parametrize("key", KEYS)
def test_a_key_pasted_into_the_model_is_neither_stored_nor_shown_again(
    rig: WebChatRig, key: str
) -> None:
    html = save(rig, kind="ollama", base_url="http://localhost:11434", model=key)

    assert key not in html
    assert field_value(html, "ai-model") is None
    assert rig.chat.store.get("chat.model") is None
    assert "looks like an API key" in html


@pytest.mark.parametrize("name", MODEL_KEYS)
def test_a_key_shaped_model_is_neither_stored_nor_shown_again(rig: WebChatRig, name: str) -> None:
    html = save(rig, kind="ollama", base_url="http://localhost:11434", model=name)

    assert name not in html
    assert field_value(html, "ai-model") is None
    assert rig.chat.store.get("chat.model") is None


@pytest.mark.parametrize("name", HOSTED_MODELS)
def test_a_hosted_model_name_is_saved_and_shown_again(rig: WebChatRig, name: str) -> None:
    html = save(rig, kind="openai_compatible", base_url="https://api.example.com/v1", model=name)

    assert field_value(html, "ai-model") == name
    assert rig.chat.store.get("chat.model") == name


def test_a_key_in_the_address_path_is_refused_and_not_shown_again(rig: WebChatRig) -> None:
    html = save(
        rig, kind="openai_compatible", base_url=f"https://x.example/v1/{GOOGLE_STYLE}", model="m"
    )

    assert GOOGLE_STYLE not in html
    assert field_value(html, "ai-base-url") is None
    assert rig.chat.store.get("chat.base_url") is None


def test_an_address_with_no_scheme_is_not_shown_again(rig: WebChatRig) -> None:
    html = save(rig, kind="ollama", base_url="mac-studio.local:11434", model="m")

    assert field_value(html, "ai-base-url") is None


def test_a_refused_but_ordinary_address_is_shown_again_so_it_can_be_fixed(rig: WebChatRig) -> None:
    html = save(rig, kind="ollama", base_url="http://example.com/v1", model="m")

    assert field_value(html, "ai-base-url") == "http://example.com/v1"


def test_an_address_with_a_fragment_is_refused_and_not_shown_again(rig: WebChatRig) -> None:
    html = save(rig, kind="ollama", base_url="https://example.com/v1#fake-frag-777", model="m")

    assert "must not carry a query string or fragment" in html
    assert "fake-frag-777" not in html


def test_an_over_long_value_is_refused_and_not_sent_back(rig: WebChatRig) -> None:
    html = save(rig, kind="ollama", base_url="http://localhost:11434", model="m" * 9000)

    assert "longer than 8192 characters" in html
    assert "mmmmmmmmmm" not in html
    assert rig.chat.store.get("chat.kind") is None


def test_the_saved_card_still_shows_ordinary_values_back(rig: WebChatRig) -> None:
    html = save(rig, kind="ollama", base_url="http://localhost:11434", model="llama3.2")

    assert field_value(html, "ai-base-url") == "http://localhost:11434"
    assert field_value(html, "ai-model") == "llama3.2"


@pytest.mark.parametrize(
    "address", ["ftp://example.com/x", "example.com", "http://", "file:///etc"]
)
def test_an_address_that_is_not_an_http_url_with_a_host_is_not_shown_again(
    rig: WebChatRig, address: str
) -> None:
    html = save(rig, kind="ollama", base_url=address, model="m")

    assert field_value(html, "ai-base-url") is None


# --- a key typed in the port or host position (found by the review) -----------------------------


@pytest.mark.parametrize("key", KEYS)
def test_a_key_in_the_port_position_is_not_shown_again(rig: WebChatRig, key: str) -> None:
    html = save(rig, kind="ollama", base_url=f"http://localhost:{key}", model="m")

    assert key not in html
    assert field_value(html, "ai-base-url") is None
    assert rig.chat.store.get("chat.base_url") is None


@pytest.mark.parametrize("key", KEYS)
def test_a_key_as_the_host_is_refused_not_stored_and_not_shown_again(
    rig: WebChatRig, key: str
) -> None:
    html = save(rig, kind="ollama", base_url=f"http://{key}:11434", model="m")

    assert key not in html
    assert 'class="flash bad"' in html  # the address guard or the key check, whichever comes first
    assert field_value(html, "ai-base-url") is None
    assert rig.chat.store.get("chat.base_url") is None


@pytest.mark.parametrize("key", KEYS)
def test_the_settings_service_refuses_a_key_as_the_host_without_echoing_it(key: str) -> None:
    with pytest.raises(InvalidChatSettingError) as raised:
        _ = normalise_provider("openai_compatible", f"https://{key}/v1", "m")

    assert key not in str(raised.value)
    assert "API key" in str(raised.value)


@pytest.mark.parametrize(
    "host", ["10.1.2.3", "192.168.1.20", "[::1]", "gpu-box.local", "localhost"]
)
def test_an_ip_literal_or_ordinary_host_is_still_accepted(host: str) -> None:
    address = normalise_provider("ollama", f"http://{host}:11434", "m")[1]

    assert address == f"http://{host}:11434"


# --- found by the second review: ordinary hosts, and a percent-encoded key ----------------------


@pytest.mark.parametrize(
    "host", ["www.example.com", "api.openai.example.org", "10.0.0.5.nip.io", "ip-10-0-0-5.local"]
)
def test_an_ordinary_dotted_host_is_not_taken_for_a_key(host: str) -> None:
    address = normalise_provider("openai_compatible", f"https://{host}/v1", "m")[1]

    assert address == f"https://{host}/v1"


def test_a_dashed_ip_name_of_six_or_more_digits_is_refused_as_a_host_the_known_cost() -> None:
    with pytest.raises(InvalidChatSettingError):
        _ = normalise_provider("ollama", "http://192-168-1-10.sslip.io:11434", "m")


@pytest.mark.parametrize("key", KEYS)
def test_a_percent_encoded_key_in_the_path_is_refused_without_echoing_it(key: str) -> None:
    encoded = "".join(f"%{ord(c):02X}" for c in key)

    with pytest.raises(InvalidChatSettingError) as raised:
        _ = normalise_provider("openai_compatible", f"https://api.example.com/v1/{encoded}", "m")

    assert encoded not in str(raised.value)
    assert "API key" in str(raised.value)


# --- card C5: key-shaped names and addresses (decisions 0290 to 0294) ----------------------------

_MIXED = "a1B2c3D4e5F6g7H8i9J0"  # 20 characters: lower, upper and a digit
KEY_ADDRESSES = [
    "https://api.example.com/v1;key=abc123def",
    "https://api.example.com/v1/token=abc12345",
    "https://api.example.com/v1/KEY=abc12345",
    "https://api.example.com/v1/Bearer-abc",
    "https://api.example.com/BEARER",
    f"https://api.example.com/v1/{_MIXED}",
    f"https://{_MIXED}.example.com/v1",
    f"https://api.{_MIXED}/v1",
    "https://a1B2c3D4e5F6g7H8%69J0k.example.com/v1",
    "https://api.example.com/v1/" + "AS" + "IAIOSFODNN7EXAMPLE",
    "https://api.example.com/v1/" + "fw" + "_abc",
    "https://api.example.com/v1/" + "sk" + "_live_abc",
    "https://api.example.com/v1/" + "gh" + "o_abc",
    "https://api.example.com/v1;" + "a",
    "https://api.example.com/v1%3Bkey%3Dabc123def",
]
REAL_ADDRESSES = [
    "https://openrouter.ai/api/v1",
    "https://api.groq.com/openai/v1",
    "https://api.together.xyz/v1",
    "http://localhost:11434",
    "http://localhost:1234/v1",
    "https://x.openai.azure.com/openai/deployments/gpt-4o",
    "http://192.168.1.20:8080/v1",
]


@pytest.mark.parametrize("address", KEY_ADDRESSES)
def test_a_key_shaped_address_is_recognised(address: str) -> None:
    assert address_holds_api_key(address)


@pytest.mark.parametrize(
    "address",
    [
        "openrouter.ai/api/v1",
        "api.groq.com/openai/v1",
        "localhost:11434",
        *REAL_ADDRESSES,
    ],
)
def test_a_real_endpoint_is_not_taken_for_a_key(address: str) -> None:
    assert not address_holds_api_key(address)


@pytest.mark.parametrize("address", KEY_ADDRESSES)
def test_a_key_shaped_address_is_refused_by_the_service_without_echoing_it(address: str) -> None:
    with pytest.raises(InvalidChatSettingError) as raised:
        _ = normalise_provider("openai_compatible", address, "m")

    assert address not in str(raised.value)
    assert "API key" in str(raised.value)


@pytest.mark.parametrize("address", REAL_ADDRESSES)
def test_a_real_endpoint_is_accepted_by_the_service(address: str) -> None:
    assert normalise_provider("openai_compatible", address, "m")[1] == address


def test_a_label_or_segment_of_19_mixed_characters_is_accepted_and_20_is_refused() -> None:
    assert not address_holds_api_key(f"https://api.example.com/v1/{_MIXED[:19]}")
    assert not address_holds_api_key(f"https://{_MIXED[:19]}.example.com/v1")
    assert address_holds_api_key(f"https://api.example.com/v1/{_MIXED}")


@pytest.mark.parametrize(
    "part", ["abcd1efgh2ijkl3mnop4", "ABCD1EFGH2IJKL3MNOP4", "AbCdEfGhIjKlMnOpQrSt"]
)
def test_a_long_segment_that_does_not_mix_case_and_a_digit_is_accepted(part: str) -> None:
    assert not address_holds_api_key(f"https://api.example.com/v1/{part}")


@pytest.mark.parametrize("address", KEY_ADDRESSES)
def test_a_key_shaped_address_is_neither_stored_nor_shown_again(
    rig: WebChatRig, address: str
) -> None:
    html = save(rig, kind="openai_compatible", base_url=address, model="m")

    assert address not in html
    assert field_value(html, "ai-base-url") is None
    assert rig.chat.store.get("chat.base_url") is None


@pytest.mark.parametrize("address", REAL_ADDRESSES)
def test_a_real_endpoint_is_saved_and_shown_again(rig: WebChatRig, address: str) -> None:
    html = save(rig, kind="openai_compatible", base_url=address, model="m")

    assert field_value(html, "ai-base-url") == address
    assert rig.chat.store.get("chat.base_url") == address


def test_a_bedrock_inference_profile_arn_is_longer_than_100_characters() -> None:
    assert len(BEDROCK_ARN) > 100
    assert not model_name_looks_like_api_key(BEDROCK_ARN)


def test_a_hex_run_of_23_is_accepted_and_24_is_refused() -> None:
    assert not model_name_looks_like_api_key("model-" + "a" * 23)
    assert model_name_looks_like_api_key("model-" + "a" * 24)


def test_a_colon_then_a_short_or_digitless_run_is_accepted() -> None:
    assert not model_name_looks_like_api_key("user:pw1234567")  # 9 characters
    assert not model_name_looks_like_api_key("llama:abcdefghijklmnop")  # no digit
    assert not model_name_looks_like_api_key("llama3.1:8b-instruct-q4_K_M")


def test_a_colon_then_a_run_of_10_with_a_digit_is_refused() -> None:
    assert model_name_looks_like_api_key("user:pw12345678")
    assert model_name_looks_like_api_key("arn:aws:x:y:pw1234567890:z")


def test_only_a_twelve_digit_account_id_between_colons_in_an_arn_is_exempt() -> None:
    assert not model_name_looks_like_api_key("arn:aws:bedrock:us-east-1:123456789012:foo/bar")
    assert model_name_looks_like_api_key("user:123456789012:foo")  # not an arn
    assert model_name_looks_like_api_key("arn:aws:bedrock:us-east-1:123456789012")  # at the end
    assert model_name_looks_like_api_key("arn:aws:bedrock:us-east-1:12345678901:foo")  # 11 digits
    assert model_name_looks_like_api_key("arn:aws:bedrock:us-east-1:1234567890123:foo")  # 13


@pytest.mark.parametrize("prefix", ["AS" + "IA", "fw" + "_", "sk" + "_live_", "sk" + "_test_"])
def test_the_new_key_prefixes_decide_even_for_a_short_model_name(prefix: str) -> None:
    assert model_name_looks_like_api_key(prefix + "x")


def test_an_email_shaped_model_name_is_refused_as_a_key_shape() -> None:
    with pytest.raises(InvalidChatSettingError) as raised:
        _ = normalise_provider("ollama", None, "a" + "@" + "b.co")

    assert "API key" in str(raised.value)


@pytest.mark.parametrize(
    "name",
    ["claude-3-5-sonnet@20240620", "claude-3-5-sonnet-v2@20241022", "m@001", "m@v2.1", "a@b"],
)
def test_an_at_sign_without_a_host_after_it_is_not_taken_for_an_email(name: str) -> None:
    assert not model_name_looks_like_api_key(name)
    assert normalise_provider("openai_compatible", "https://api.example.com/v1", name)[2] == name


@pytest.mark.parametrize("name", ["m@host.com", "m@x.y", "m@a-b.example.com", "m@a1.b"])
def test_an_at_sign_then_a_host_like_part_is_taken_for_an_email(name: str) -> None:
    assert model_name_looks_like_api_key(name)
