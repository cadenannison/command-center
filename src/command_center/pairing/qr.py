"""The pairing QR code: a small JSON payload drawn as an SVG, with no imaging library."""

import json
from typing import Any, cast

import qrcode
from qrcode.image.svg import SvgPathImage

PAYLOAD_VERSION = 1
_QUIET_ZONE_MODULES = 2


def pairing_payload(url: str, token: str) -> str:
    """The text the phone scans: where the Mac is and the one-time token, as JSON.

    The token travels in the body, never in a URL (AGENTS.md rule 5): URLs end up in logs,
    history and referrers.
    """
    return json.dumps({"v": PAYLOAD_VERSION, "url": url, "token": token}, separators=(",", ":"))


def qr_svg(payload: str) -> str:
    """An inline `<svg>` of the QR code for payload. Pure vector paths; pillow is not needed."""
    # qrcode ships no type information, so its calls are typed here once.
    make = cast("Any", qrcode.make)
    image = make(payload, image_factory=SvgPathImage, border=_QUIET_ZONE_MODULES)
    return bytes(image.to_string(xml_declaration=False)).decode("utf-8")
