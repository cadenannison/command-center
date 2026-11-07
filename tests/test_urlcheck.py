"""SSRF guard: only https URLs to public hosts."""

import pytest

from command_center.core.urlcheck import require_https_public


@pytest.mark.parametrize(
    "url",
    [
        "https://canvas.example.edu",
        "https://canvas.example.edu/api/v1/courses?per_page=50",
        "https://CALENDAR.example.com:8443/feed.ics",
        "https://8.8.8.8/x",
        "https://[2606:4700:4700::1111]/x",
        "https://[64:ff9b::808:808]/x",
    ],
)
def test_public_https_urls_are_returned_unchanged(url: str) -> None:
    assert require_https_public(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://canvas.example.edu",
        "ftp://canvas.example.edu",
        "file:///etc/passwd",
        "//canvas.example.edu",
        "canvas.example.edu",
        "",
        "https://",
        "https:///path",
    ],
)
def test_non_https_or_hostless_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="https"):
        require_https_public(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://user@example.com/",
        "https://user:pass@example.com/",
        "https://:pass@example.com/",
        "https://example.com@evil.example/",
    ],
)
def test_urls_with_userinfo_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="credentials"):
        require_https_public(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/",
        "https://LOCALHOST:8000/",
        "https://localhost./",
        "https://app.localhost/",
        "https://printer.local/",
        "https://Printer.LOCAL./",
    ],
)
def test_local_hostnames_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="local"):
        require_https_public(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://127.1.2.3/",
        "https://10.0.0.5/",
        "https://172.16.0.1/",
        "https://172.31.255.255/",
        "https://192.168.1.1/",
        "https://169.254.169.254/latest/meta-data",
        "https://0.0.0.0/",
        "https://[::1]/",
        "https://[fe80::1]/",
        "https://[fc00::1]/",
        "https://[::ffff:127.0.0.1]/",
        "https://[::ffff:10.0.0.1]/",
        "https://100.100.100.100/",
        "https://100.64.0.1/",
        "https://[64:ff9b::7f00:1]/",
        "https://[::7f00:1]/",
        "https://[2002:7f00:1::]/",
        "https://[fec0::1]/",
        "https://224.0.0.1/",
        "https://[ff02::1]/",
    ],
)
def test_private_loopback_and_link_local_ips_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="private"):
        require_https_public(url)


@pytest.mark.parametrize(
    "url", ["https://2130706433/", "https://0x7f000001/", "https://017700000001/"]
)
def test_numeric_host_spellings_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="numeric"):
        require_https_public(url)


@pytest.mark.parametrize(
    "url", ["https://exa mple.com/", "https://example.com/\nx", "https://example.com:notaport/"]
)
def test_malformed_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="malformed"):
        require_https_public(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1\\.example.com/",
        "https://127.0.0.1\\@example.com/",
        "https://\uff11\uff12\uff17.\uff10.\uff10.\uff11/",
        "https://%31%32%37.0.0.1/",
        "https://exa%6Dple.com/",
        "https://exa_mple.com/",
        "https://b\u00fccher.example/",
        "https://example.com\\evil.com/",
    ],
)
def test_hostnames_with_characters_outside_ascii_letters_digits_hyphen_dot_are_rejected(
    url: str,
) -> None:
    with pytest.raises(ValueError, match="Rejected URL"):
        require_https_public(url)


_SECRET = "fake-s3cret"  # noqa: S105  (a marker the messages must not echo)
_FULLWIDTH_HASH = "\uff03"  # NFKC-unsafe in a netloc, so urlsplit raises and quotes the netloc
_FULLWIDTH_SLASH = "\uff0f"


@pytest.mark.parametrize(
    "url",
    [
        f"https://user:{_SECRET}{_FULLWIDTH_HASH}@example.com/",
        f"https://user:{_SECRET}{_FULLWIDTH_SLASH}@example.com/",
        f"https://user:{_SECRET}@example.com/",
        f"https://{_SECRET}@example.com/",
        f"https://:{_SECRET}@example.com/",
        f"https://example.com@{_SECRET}.example/",
        f"https://user:{_SECRET}@[::1/",
        f"https://user:{_SECRET}@example.com:notaport/",
        f"https://user:{_SECRET}@127.0.0.1/",
        f"https://user:{_SECRET} @example.com/",
        f"http://user:{_SECRET}@example.com/",
        f"https://{_SECRET}.localhost/",
        f"https://{_SECRET}.local/",
        f"https://{_SECRET}.0x7f/",
        f"https://{_SECRET}_x.example/",
        f"https://{_SECRET}\\.example.com/",
    ],
)
def test_error_messages_never_echo_any_part_of_the_url(url: str) -> None:
    with pytest.raises(ValueError, match="Rejected URL") as excinfo:
        require_https_public(url)

    assert _SECRET not in str(excinfo.value)
    assert "example.com" not in str(excinfo.value)


def test_unparseable_url_error_carries_neither_cause_nor_context() -> None:
    # The parser's own exception quotes the netloc, credentials included, so it must not be chained.
    with pytest.raises(ValueError, match="malformed") as excinfo:
        require_https_public(f"https://user:{_SECRET}{_FULLWIDTH_HASH}@example.com/")

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
