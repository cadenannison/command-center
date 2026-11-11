"""Redaction of http(s) URLs and token-like runs."""

import time
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from command_center.core.redact import redact

_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_RUN_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
_ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("see https://example.com/a now", "see [url] now"),
        ("see http://example.com now", "see [url] now"),
        ("see HTTPS://EXAMPLE.COM/A now", "see [url] now"),
        ("see HtTp://example.com now", "see [url] now"),
        ("open https://user@example.com/x ok", "open [url] ok"),
        ("open https://user:pw@example.com/x ok", "open [url] ok"),
        ("go to https://example.com/page.", "go to [url]"),
        (
            "feed https://example.com/feeds/ical?token=fake-abcDEF1234567890 added",
            "feed [url] added",
        ),
        ("a https://x.io/1 b https://y.io/2 c", "a [url] b [url] c"),
        ("ftp://example.com/a stays", "[url] stays"),
        ("plain https: no", "plain https: no"),
    ],
)
def test_redact_masks_http_urls(text: str, expected: str) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("key " + "a1" * 11 + "b1" + " end", "key [token] end"),
        ("key " + "a" * 22 + "1" + " end", "key " + "a" * 22 + "1 end"),
        ("key " + "a" * 23 + "1" + " end", "key [token] end"),
        ("key " + "a" * 24 + " end", "key " + "a" * 24 + " end"),
        ("key " + "a" * 60 + " end", "key [token] end"),
        ("key " + "ab-" * 12 + " end", "key [token] end"),
        ("key " + "ab_" * 12 + "9 end", "key [token] end"),
        ("key fake-" + "a" * 18 + "1 end", "key [token] end"),
        ("key fake-" + "a" * 17 + "1 end", "key fake-" + "a" * 17 + "1 end"),
        ("key (" + "a" * 23 + "1) end", "key ([token]) end"),
        ("key " + "a" * 24 + "1" + "é end", "key [token]é end"),
        ("due 2026-11-07 ok", "due 2026-11-07 ok"),
    ],
)
def test_redact_masks_token_like_runs_of_24_with_a_digit(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_redact_keeps_a_token_of_23_and_masks_one_of_24() -> None:
    assert redact("x" * 22 + "1") == "x" * 22 + "1"
    assert redact("x" * 23 + "1") == "[token]"


def test_redact_removes_a_token_inside_an_email_or_url() -> None:
    run = "abcDEF1234567890abcDEF1234567890"

    assert redact(f"{run}@school.edu") == "[email]"
    assert redact(f"me@{run}.edu") == "[email]"
    assert redact(f"https://x.io/{run}") == "[url]"


@pytest.mark.parametrize(
    "text",
    [
        "see https://example.com/a?t=abcDEF1234567890 now",
        "mail user@example.com or " + "a1" * 20,
        "[url] [token] [email] [number]",
        "https://a.b/" + "9" * 40,
        "x" * 30 + "1",
        "call 801-555-1234 at https://x.io/y",
        "https://",
        "http://http://x",
    ],
)
def test_redact_is_idempotent_for_url_and_token_markers(text: str) -> None:
    once = redact(text)

    assert redact(once) == once


def test_redact_does_not_rematch_its_own_markers() -> None:
    assert redact("[url] and [token]") == "[url] and [token]"


@given(st.text())
def test_redact_is_idempotent_on_arbitrary_text(text: str) -> None:
    once = redact(text)

    assert redact(once) == once


@given(
    st.text(
        alphabet=st.sampled_from(list("https:/@.-_[]()0123456789 abxyz")),
        max_size=80,
    )
)
def test_redact_is_idempotent_on_url_and_token_shaped_text(text: str) -> None:
    once = redact(text)

    assert redact(once) == once


_WORDS = st.text(alphabet=_LETTERS + "'", min_size=1, max_size=12)
_ISO_DATES = st.dates(min_value=date(1000, 1, 1), max_value=date(9999, 12, 31)).map(
    lambda day: day.isoformat()
)


@given(st.lists(_WORDS | _ISO_DATES, max_size=30))
def test_redact_leaves_letter_words_and_iso_dates_untouched(parts: list[str]) -> None:
    text = " ".join(parts)

    assert redact(text) == text


@given(
    st.text(),
    st.text(alphabet=_RUN_ALPHABET, min_size=24).filter(
        lambda tail: any(c.isdigit() for c in tail)
    ),
    st.text(),
)
def test_redact_never_lets_a_fake_token_survive(before: str, tail: str, after: str) -> None:
    token = "fake-" + tail

    assert token not in redact(f"{before} {token} {after}")
    assert tail not in redact(f"{before} {token} {after}")


def _host(label: str, tld: str) -> str:
    return f"{label}.{tld}"


_HOSTS = st.builds(
    _host,
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=10),
    st.sampled_from(["com", "org", "edu", "io"]),
)
_PATHS = st.lists(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=8),
    min_size=1,
    max_size=4,
).map("/".join)
_QUERY_VALUES = st.text(alphabet=_ALNUM, min_size=12, max_size=40)


@given(
    st.sampled_from(["http", "https", "HTTPS"]),
    _HOSTS,
    _PATHS,
    st.sampled_from(["token", "key", "secret"]),
    _QUERY_VALUES,
)
def test_redact_never_lets_a_feed_url_survive(
    scheme: str, host: str, path: str, name: str, value: str
) -> None:
    url = f"{scheme}://{host}/{path}/ical?{name}={value}"

    result = redact(f"Subscribe to {url} today")

    assert url not in result
    assert value not in result
    assert host not in result
    assert result == "Subscribe to [url] today"


_LONG = 100_000
_TIME_BUDGET_SECONDS = 5.0


@pytest.mark.parametrize(
    "text",
    [
        "a" * (2 * _LONG),
        "a1" * _LONG,
        "a-" * _LONG,
        "a" * 23 + " " + ("a" * 23 + " ") * _LONG,
        "a" * 23 + "1" + " " + ("a" * 23 + "1 ") * (_LONG // 10),
        "http://" * _LONG,
        "https://" + "@" * _LONG,
        "https:/" * _LONG,
        "http://a " * _LONG,
        "a" * 23 + "@" + "1" * 23 + " " + "a1" * _LONG,
        ("a" * 24 + "-") * (_LONG // 5) + "1",
        "[token]" * _LONG,
        "[url]" * _LONG,
    ],
    ids=[
        "one-long-letter-run",
        "one-long-token",
        "one-long-dashed-run",
        "many-runs-of-23-letters",
        "many-tokens-of-24",
        "scheme-only-repeated",
        "scheme-then-at-signs",
        "almost-scheme-repeated",
        "many-short-urls",
        "email-then-token",
        "dash-joined-runs-digit-last",
        "marker-repeated",
        "url-marker-repeated",
    ],
)
def test_redact_finishes_quickly_on_long_url_and_token_input(text: str) -> None:
    started = time.perf_counter()
    redact(text)

    assert time.perf_counter() - started < _TIME_BUDGET_SECONDS
