"""Chat base URL guard: https to public hosts, plus http or https to local hosts."""

import ipaddress

import pytest
from hypothesis import given
from hypothesis import strategies as st

from command_center.core.urlcheck import require_chat_base_url

_SCHEMES = ("http", "https")

LOCAL_HOSTS = [
    "localhost",
    "LOCALHOST",
    "localhost.",
    "app.localhost",
    "printer.local",
    "Printer.LOCAL.",
    "gpu-box",
    "GPU-Box.",
    "127.0.0.1",
    "127.1.2.3",
    "[::1]",
    "10.0.0.5",
    "10.255.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.20",
    "[fc00::1]",
    "[fd12:3456:789a::1]",
    "[FD12:3456:789A::1]",
    "[::ffff:127.0.0.1]",
    "[::ffff:10.0.0.1]",
    "[::ffff:192.168.1.1]",
]

ALWAYS_REFUSED_HOSTS = [
    "169.254.169.254",
    "169.254.0.1",
    "169.254.255.255",
    "[fe80::1]",
    "[FE80::1]",
    "[febf::1]",
    "0.0.0.0",  # noqa: S104  (a refused address, not a bind)
    "[::]",
    "224.0.0.1",
    "239.255.255.250",
    "[ff02::1]",
    "metadata.google.internal",
    "METADATA.GOOGLE.INTERNAL.",
    "metadata",
    "Metadata.",
    "100.100.100.200",
    "[fd00:ec2::254]",
    "[FD00:EC2::254]",
    "[::ffff:169.254.169.254]",
    "[::ffff:100.100.100.200]",
    "[::ffff:0.0.0.0]",
    "[::ffff:224.0.0.1]",
    "[64:ff9b::a9fe:a9fe]",
    "[::a9fe:a9fe]",
    "2130706433",
    "0x7f.1",
    "0x7f000001",
    "017700000001",
    "127.1.2.3.4",
]


@pytest.mark.parametrize("scheme", _SCHEMES)
@pytest.mark.parametrize("host", LOCAL_HOSTS)
def test_local_hosts_are_accepted_over_http_and_https(scheme: str, host: str) -> None:
    url = f"{scheme}://{host}/v1"

    assert require_chat_base_url(url) == url


@pytest.mark.parametrize("scheme", _SCHEMES)
@pytest.mark.parametrize("host", ALWAYS_REFUSED_HOSTS)
def test_metadata_link_local_and_odd_hosts_are_refused_even_over_https(
    scheme: str, host: str
) -> None:
    with pytest.raises(ValueError, match="Rejected URL"):
        require_chat_base_url(f"{scheme}://{host}/")


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://[::ffff:169.254.169.254]/",
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_cloud_metadata_urls_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match="Rejected URL"):
        require_chat_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "https://API.Example.COM:8443/v1/",
        "https://8.8.8.8",
        "https://[2606:4700:4700::1111]/v1",
        "http://localhost:11434/v1",
        "http://192.168.1.20:8080/v1",
        "http://10.0.0.5",
        "http://[::1]:11434",
        "http://gpu-box:11434",
    ],
)
def test_accepted_urls_are_returned_unchanged(url: str) -> None:
    assert require_chat_base_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://api.openai.com/v1",
        "http://example.com",
        "http://8.8.8.8",
        "http://[2606:4700:4700::1111]/",
        "http://100.64.0.1/",
        "https://100.64.0.1/",
        "http://192.0.2.1/",
        "https://192.0.2.1/",
        "https://198.51.100.7/",
        "https://[2001:db8::1]/",
        "http://0.1.2.3/",
        "http://172.32.0.1/",
        "http://172.15.0.1/",
        "http://192.169.0.1/",
        "http://11.0.0.1/",
    ],
)
def test_public_http_and_non_global_addresses_outside_the_local_ranges_are_refused(
    url: str,
) -> None:
    with pytest.raises(ValueError, match="Rejected URL"):
        require_chat_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://localhost",
        "file:///etc/passwd",
        "ws://localhost/",
        "//localhost",
        "localhost:11434",
        "localhost",
        "",
        "http://",
        "http:///path",
        "https://",
    ],
)
def test_other_schemes_and_hostless_urls_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match="Rejected URL"):
        require_chat_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/?key=x",
        "http://localhost/v1?",
        "http://localhost/v1#frag",
        "https://api.example.com/v1?api_key=x",
        "https://api.example.com/v1#key=x",
    ],
)
def test_query_strings_and_fragments_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match="query"):
        require_chat_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/ v1",
        "http://local host/",
        "http://localhost/\nx",
        "http://localhost/\x00",
        "http://localhost:notaport/",
        "http://[::1/",
    ],
)
def test_malformed_urls_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match="malformed"):
        require_chat_base_url(url)


_SECRET = "fake-s3cret"  # noqa: S105  (a marker the messages must not echo)


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pw@localhost/",
        "https://user:pw@localhost/",
        "http://user@localhost/",
        "http://:pw@localhost/",
        "http://localhost@example.com/",
        "http://user:pw@169.254.169.254/",
    ],
)
def test_userinfo_is_refused_and_the_message_echoes_nothing(url: str) -> None:
    with pytest.raises(ValueError, match="credentials") as excinfo:
        require_chat_base_url(url)

    message = str(excinfo.value)
    assert "user" not in message
    assert "pw" not in message
    assert "localhost" not in message


@pytest.mark.parametrize(
    "url",
    [
        f"http://{_SECRET}.example/",
        f"https://{_SECRET}@localhost/",
        f"http://localhost:{_SECRET}/",
        f"http://{_SECRET}_x/",
        f"http://{_SECRET}.0x7f/",
        f"http://[{_SECRET}]/",
        f"http://localhost/?key={_SECRET}",
        f"http://localhost/#{_SECRET}",
        f"http://localhost/ {_SECRET}",
        f"ftp://{_SECRET}.localhost/",
        f"http://169.254.169.254/{_SECRET}",
        f"https://{_SECRET}.local:badport/",
    ],
)
def test_error_messages_never_echo_any_part_of_the_url(url: str) -> None:
    with pytest.raises(ValueError, match="Rejected URL") as excinfo:
        require_chat_base_url(url)

    assert _SECRET not in str(excinfo.value)
    assert "localhost" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


@given(
    octets=st.tuples(st.just(169), st.just(254), st.integers(0, 255), st.integers(0, 255)),
    scheme=st.sampled_from(_SCHEMES),
)
def test_every_link_local_ipv4_is_refused(octets: tuple[int, int, int, int], scheme: str) -> None:
    host = ".".join(str(octet) for octet in octets)

    with pytest.raises(ValueError, match="Rejected URL"):
        require_chat_base_url(f"{scheme}://{host}/")


@given(
    first=st.sampled_from([10, 127]),
    rest=st.tuples(st.integers(0, 255), st.integers(0, 255), st.integers(0, 255)),
    scheme=st.sampled_from(_SCHEMES),
)
def test_every_loopback_and_ten_net_ipv4_is_accepted(
    first: int, rest: tuple[int, int, int], scheme: str
) -> None:
    url = f"{scheme}://{first}.{rest[0]}.{rest[1]}.{rest[2]}:8080/v1"

    assert require_chat_base_url(url) == url


@given(
    address=st.ip_addresses(v=4).filter(lambda a: a.is_global and not a.is_multicast),
)
def test_every_global_ipv4_needs_https(address: ipaddress.IPv4Address) -> None:
    assert require_chat_base_url(f"https://{address}/v1") == f"https://{address}/v1"
    with pytest.raises(ValueError, match="Rejected URL"):
        require_chat_base_url(f"http://{address}/v1")


@given(url=st.text(max_size=80))
def test_arbitrary_text_only_ever_raises_value_error(url: str) -> None:
    try:
        result = require_chat_base_url(url)
    except ValueError:
        return
    assert result == url


@given(host=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.", min_size=1, max_size=30))
def test_a_refusal_never_contains_the_host(host: str) -> None:
    marker = f"zq{host}"
    with pytest.raises(ValueError, match="Rejected URL") as excinfo:
        require_chat_base_url(f"http://{marker}:99999999/x")

    assert marker not in str(excinfo.value)
