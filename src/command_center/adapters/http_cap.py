"""The reply-size cap shared by the chat providers and the city search (decisions 0222, 0246).

One implementation of "read a streamed body, stop at the cap", so the limit and the way it is
counted cannot drift between callers. Each caller turns `ReplyTooLarge` into its own fixed-text
error: this module knows no provider names, URLs or bodies.
"""

import httpx

MAX_REPLY_BYTES = 1_048_576  # about 1 MB


class ReplyTooLarge(Exception):  # noqa: N818  (reads as a condition, like StopIteration)
    """A reply is, or says it will be, over the cap."""


async def read_capped(response: httpx.Response, limit: int = MAX_REPLY_BYTES) -> bytes:
    """The decoded body, or ReplyTooLarge once it is (or declares it will be) over `limit`.

    The count is of decoded bytes, so a compressed reply is stopped at the cap too, give or take
    one network read: a read is decoded whole before it is counted, so a hostile gzip can overshoot
    by that read's expansion (about 1000 to 1, from 64 KiB), not by the reply's (decision 0222).
    """
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise ReplyTooLarge
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise ReplyTooLarge
    return bytes(body)
