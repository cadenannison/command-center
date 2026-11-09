"""Waiting for a worker to be inside an adapter's fetch, for the chaos tests (decision 0088)."""

import asyncio

import pytest

from fake_adapter import FakeAdapter

FETCH_WAIT_SECONDS = 10.0  # a bound for a hang, not a delay: the loop yields, it never sleeps


async def until_fetching(adapter: FakeAdapter, wait_seconds: float = FETCH_WAIT_SECONDS) -> None:
    """Return once a worker is inside `adapter.fetch`; fail the test if none gets there in time."""
    try:
        async with asyncio.timeout(wait_seconds):
            while adapter.in_flight == 0:  # noqa: ASYNC110  (the fake exposes a counter, no event)
                await asyncio.sleep(0)
    except TimeoutError:
        pytest.fail(
            f"No worker started fetching within {wait_seconds:g} s: the job was never consumed, "
            "or the worker died before it called the adapter"
        )
