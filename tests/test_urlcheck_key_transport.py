"""Where an API key may travel: https anywhere the chat guard allows, http only to loopback."""

import pytest

from command_center.core.urlcheck import may_send_key

LOOPBACK_HOSTS = [
    "localhost",
    "LOCALHOST",
    "127.0.0.1",
    "127.1.2.3",
    "[::1]",
    "[::ffff:127.0.0.1]",
]

NOT_LOOPBACK_HOSTS = [
    "localhost.",  # a different DNS name from localhost (decision 0221)
    "127.0.0.1.",
    "gpu-box",
    "GPU-Box.",
    "mac.local",
    "Printer.LOCAL.",
    "app.localhost",
    "192.168.1.20",
    "10.0.0.5",
    "172.16.0.1",
    "[fd12:3456:789a::1]",
    "[fc00::1]",
    "[::ffff:10.0.0.1]",
    "[::ffff:192.168.1.1]",
]


@pytest.mark.parametrize("host", LOOPBACK_HOSTS)
def test_a_key_may_go_over_http_to_a_loopback_name_or_address(host: str) -> None:
    assert may_send_key(f"http://{host}:8080/v1") is True


@pytest.mark.parametrize("host", NOT_LOOPBACK_HOSTS)
def test_a_key_may_not_go_over_http_to_a_lan_or_single_label_host(host: str) -> None:
    assert may_send_key(f"http://{host}:8080/v1") is False


@pytest.mark.parametrize("host", [*LOOPBACK_HOSTS, *NOT_LOOPBACK_HOSTS, "llm.example.com"])
def test_a_key_may_go_over_https_to_any_host_the_chat_guard_allows(host: str) -> None:
    assert may_send_key(f"https://{host}/v1") is True


@pytest.mark.parametrize(
    "url",
    [
        "http://api.openai.com/v1",
        "http://169.254.169.254/v1",
        "ftp://localhost/",
        "http://localhost/v1?key=x",
        "http://user:pw@localhost/v1",
    ],
)
def test_a_url_the_chat_guard_refuses_is_a_value_error_not_a_yes(url: str) -> None:
    with pytest.raises(ValueError, match="Rejected URL"):
        _ = may_send_key(url)
