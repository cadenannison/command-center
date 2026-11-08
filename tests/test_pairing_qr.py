"""The pairing QR: a JSON payload drawn as an SVG, with no imaging library."""

import json

from command_center.pairing.qr import pairing_payload, qr_svg

TOKEN = "fake-token-0000000000"  # noqa: S105
URL = "https://mac.tail1234.ts.net"


def test_the_payload_is_compact_json_with_the_url_and_the_token() -> None:
    payload = pairing_payload(URL, TOKEN)
    assert json.loads(payload) == {"v": 1, "url": URL, "token": TOKEN}
    assert " " not in payload


def test_the_token_is_in_the_payload_not_in_a_url() -> None:
    assert "?" not in pairing_payload(URL, TOKEN)
    assert f"{URL}/{TOKEN}" not in pairing_payload(URL, TOKEN)


def test_the_svg_is_an_svg_document_fragment() -> None:
    svg = qr_svg(pairing_payload(URL, TOKEN))
    assert svg.lstrip().startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    assert "<?xml" not in svg


def test_the_svg_draws_paths_and_embeds_no_raster_image() -> None:
    svg = qr_svg(pairing_payload(URL, TOKEN))
    assert "<path" in svg
    assert "<image" not in svg
    assert "base64" not in svg


def test_the_svg_does_not_contain_the_token_as_text() -> None:
    assert TOKEN not in qr_svg(pairing_payload(URL, TOKEN))


def test_different_payloads_draw_different_codes() -> None:
    assert qr_svg(pairing_payload(URL, TOKEN)) != qr_svg(pairing_payload(URL, TOKEN + "x"))


def test_the_same_payload_draws_the_same_code() -> None:
    assert qr_svg(pairing_payload(URL, TOKEN)) == qr_svg(pairing_payload(URL, TOKEN))
