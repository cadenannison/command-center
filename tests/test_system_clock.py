"""SystemClock returns real time, so only its shape is asserted."""

from datetime import timedelta

from command_center.adapters.system_clock import SystemClock
from command_center.core.ports import Clock


def test_now_is_timezone_aware_utc() -> None:
    assert SystemClock().now().utcoffset() == timedelta(0)


def test_system_clock_satisfies_the_clock_port() -> None:
    clock: Clock = SystemClock()
    assert clock.now() <= clock.now()
