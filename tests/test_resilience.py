"""Retry policy and circuit breaker: bounds, monotonic backoff, never half-open before cool-down."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from builders import NOW
from command_center.core.resilience import (
    DEFAULT_RETRY_POLICY,
    DEFAULT_VISIBILITY_TIMEOUT,
    BreakerPhase,
    BreakerState,
    CircuitBreaker,
    RetryPolicy,
)
from fakes import FakeClock


class ScriptedRng:
    """An Rng that returns the given draws in order, then repeats the last."""

    def __init__(self, draws: Sequence[float]) -> None:
        self._draws = list(draws)
        self.calls = 0

    def random(self) -> float:
        draw = self._draws[min(self.calls, len(self._draws) - 1)]
        self.calls += 1
        return draw


unit_floats = st.floats(min_value=0.0, max_value=1.0, exclude_max=True)


@st.composite
def policies(draw: st.DrawFn) -> RetryPolicy:
    base = timedelta(milliseconds=draw(st.integers(min_value=1, max_value=600_000)))
    extra = timedelta(milliseconds=draw(st.integers(min_value=0, max_value=3_600_000)))
    return RetryPolicy(
        max_attempts=draw(st.integers(min_value=1, max_value=50)),
        base_delay=base,
        factor=draw(st.floats(min_value=1.0, max_value=10.0)),
        cap=base + extra,
    )


SMALL = RetryPolicy(
    max_attempts=3, base_delay=timedelta(seconds=5), factor=2.0, cap=timedelta(minutes=5)
)


# ---------------------------------------------------------------- RetryPolicy


def test_default_policy_values() -> None:
    assert DEFAULT_RETRY_POLICY.max_attempts == 5
    assert DEFAULT_RETRY_POLICY.base_delay == timedelta(seconds=5)
    assert DEFAULT_RETRY_POLICY.factor == 2.0
    assert DEFAULT_RETRY_POLICY.cap == timedelta(minutes=5)
    assert DEFAULT_VISIBILITY_TIMEOUT.total_seconds() == 300


@pytest.mark.parametrize(
    ("max_attempts", "base_delay", "factor", "cap"),
    [
        (0, timedelta(seconds=1), 2.0, timedelta(seconds=10)),
        (3, timedelta(0), 2.0, timedelta(seconds=10)),
        (3, timedelta(seconds=-1), 2.0, timedelta(seconds=10)),
        (3, timedelta(seconds=1), 0.9, timedelta(seconds=10)),
        (3, timedelta(seconds=10), 2.0, timedelta(seconds=9)),
    ],
)
def test_policy_rejects_invalid_values(
    max_attempts: int, base_delay: timedelta, factor: float, cap: timedelta
) -> None:
    with pytest.raises(ValueError, match="RetryPolicy"):
        RetryPolicy(max_attempts=max_attempts, base_delay=base_delay, factor=factor, cap=cap)


def test_policy_accepts_boundary_values() -> None:
    policy = RetryPolicy(
        max_attempts=1, base_delay=timedelta(seconds=1), factor=1.0, cap=timedelta(seconds=1)
    )

    assert policy.exhausted(1)


def test_first_delay_is_base_delay_without_drawing_randomness() -> None:
    rng = ScriptedRng([0.7])

    assert SMALL.delay(1, rng) == timedelta(seconds=5)
    assert rng.calls == 0


def test_delay_interpolates_between_previous_and_current_step() -> None:
    assert SMALL.delay(2, ScriptedRng([0.0])) == timedelta(seconds=5)
    assert SMALL.delay(2, ScriptedRng([0.5])) == timedelta(seconds=7.5)
    assert SMALL.delay(3, ScriptedRng([0.0])) == timedelta(seconds=10)
    assert SMALL.delay(3, ScriptedRng([0.5])) == timedelta(seconds=15)


def test_delay_reaches_cap_and_stays_there() -> None:
    assert SMALL.delay(20, ScriptedRng([0.0])) == timedelta(minutes=5)
    assert SMALL.delay(20, ScriptedRng([0.999])) == timedelta(minutes=5)


def test_delay_rejects_attempt_below_one() -> None:
    with pytest.raises(ValueError, match="attempt"):
        SMALL.delay(0, ScriptedRng([0.0]))


@pytest.mark.parametrize("draw", [-0.1, 1.0, float("nan")])
def test_delay_rejects_rng_outside_unit_interval(draw: float) -> None:
    with pytest.raises(ValueError, match="Rng"):
        SMALL.delay(2, ScriptedRng([draw]))


@pytest.mark.parametrize(("attempt", "expected"), [(1, False), (2, False), (3, True), (4, True)])
def test_exhausted_when_attempt_reaches_max(attempt: int, expected: bool) -> None:  # noqa: FBT001
    assert SMALL.exhausted(attempt) is expected


@given(policies(), st.integers(min_value=1, max_value=10**6), unit_floats)
def test_delay_never_exceeds_cap(policy: RetryPolicy, attempt: int, draw: float) -> None:
    assert policy.delay(attempt, ScriptedRng([draw])) <= policy.cap


@given(policies(), st.integers(min_value=1, max_value=10**6), unit_floats)
def test_delay_is_at_least_base_delay(policy: RetryPolicy, attempt: int, draw: float) -> None:
    assert policy.delay(attempt, ScriptedRng([draw])) >= policy.base_delay


@given(policies(), st.lists(unit_floats, min_size=2, max_size=60))
def test_delay_never_decreases_as_attempt_grows_for_any_draws(
    policy: RetryPolicy, draws: list[float]
) -> None:
    delays = [
        policy.delay(attempt, ScriptedRng([draw])) for attempt, draw in enumerate(draws, start=1)
    ]

    assert delays == sorted(delays)


@given(policies())
def test_first_delay_equals_base_delay_for_any_policy(policy: RetryPolicy) -> None:
    assert policy.delay(1, ScriptedRng([0.99])) == policy.base_delay


@given(policies(), unit_floats, unit_floats)
def test_delay_is_monotonic_in_the_draw(policy: RetryPolicy, low: float, high: float) -> None:
    low, high = sorted((low, high))

    assert policy.delay(3, ScriptedRng([low])) <= policy.delay(3, ScriptedRng([high]))


@given(policies(), st.integers(min_value=1, max_value=200))
def test_exhausted_matches_max_attempts(policy: RetryPolicy, attempt: int) -> None:
    assert policy.exhausted(attempt) == (attempt >= policy.max_attempts)


def test_huge_attempt_with_large_factor_does_not_overflow() -> None:
    policy = RetryPolicy(
        max_attempts=5, base_delay=timedelta(seconds=1), factor=10.0, cap=timedelta(hours=1)
    )

    assert policy.delay(10**6, ScriptedRng([0.5])) == timedelta(hours=1)


# ---------------------------------------------------------------- CircuitBreaker

COOL = timedelta(seconds=30)


def make_breaker(threshold: int = 3) -> tuple[CircuitBreaker, FakeClock]:
    clock = FakeClock(NOW)
    return CircuitBreaker(failure_threshold=threshold, cool_down=COOL, clock=clock), clock


def test_initial_state_is_closed_with_no_failures() -> None:
    breaker, _ = make_breaker()

    assert breaker.initial() == BreakerState(phase=BreakerPhase.CLOSED, failures=0, opened_at=None)


def test_breaker_phase_values_are_stable_strings() -> None:
    assert [phase.value for phase in BreakerPhase] == ["closed", "open", "half_open"]


@pytest.mark.parametrize(("threshold", "cool_down"), [(0, COOL), (-1, COOL), (1, timedelta(0))])
def test_breaker_rejects_invalid_config(threshold: int, cool_down: timedelta) -> None:
    with pytest.raises(ValueError, match="CircuitBreaker"):
        CircuitBreaker(failure_threshold=threshold, cool_down=cool_down, clock=FakeClock(NOW))


def test_state_with_open_phase_needs_opened_at() -> None:
    with pytest.raises(ValueError, match="opened_at"):
        BreakerState(phase=BreakerPhase.OPEN, failures=3)


def test_state_rejects_negative_failures() -> None:
    with pytest.raises(ValueError, match="failures"):
        BreakerState(failures=-1)


def test_state_rejects_naive_opened_at() -> None:
    with pytest.raises(ValueError, match="opened_at"):
        BreakerState(
            phase=BreakerPhase.OPEN,
            failures=3,
            opened_at=datetime(2026, 11, 7, 12, 0),  # noqa: DTZ001
        )


def test_failures_below_threshold_keep_breaker_closed() -> None:
    breaker, _ = make_breaker(threshold=3)
    state = breaker.record_failure(breaker.record_failure(breaker.initial()))

    assert state.phase is BreakerPhase.CLOSED
    assert state.failures == 2
    assert breaker.allow(state)


def test_reaching_threshold_opens_with_current_time() -> None:
    breaker, clock = make_breaker(threshold=2)
    state = breaker.record_failure(breaker.initial())
    clock.advance(timedelta(seconds=4))
    state = breaker.record_failure(state)

    assert state == BreakerState(BreakerPhase.OPEN, 2, clock.now())
    assert not breaker.allow(state)


def test_threshold_of_one_opens_on_first_failure() -> None:
    breaker, _ = make_breaker(threshold=1)

    assert breaker.record_failure(breaker.initial()).phase is BreakerPhase.OPEN


def test_success_resets_failure_count_while_closed() -> None:
    breaker, _ = make_breaker(threshold=3)
    state = breaker.record_failure(breaker.record_failure(breaker.initial()))

    assert breaker.record_success(state) == breaker.initial()


def test_open_breaker_stays_open_until_cool_down_elapses() -> None:
    breaker, clock = make_breaker(threshold=1)
    state = breaker.record_failure(breaker.initial())

    clock.advance(COOL - timedelta(microseconds=1))

    assert breaker.current(state).phase is BreakerPhase.OPEN
    assert not breaker.allow(state)


def test_open_breaker_half_opens_exactly_at_cool_down() -> None:
    breaker, clock = make_breaker(threshold=1)
    state = breaker.record_failure(breaker.initial())

    clock.advance(COOL)
    current = breaker.current(state)

    assert current == BreakerState(BreakerPhase.HALF_OPEN, 1, state.opened_at)
    assert breaker.allow(state)


def test_current_leaves_closed_and_half_open_states_unchanged() -> None:
    breaker, clock = make_breaker(threshold=1)
    closed = breaker.initial()
    half_open = BreakerState(BreakerPhase.HALF_OPEN, 1, clock.now())

    assert breaker.current(closed) is closed
    assert breaker.current(half_open) is half_open


def test_success_in_half_open_closes_breaker() -> None:
    breaker, clock = make_breaker(threshold=1)
    state = breaker.record_failure(breaker.initial())
    clock.advance(COOL)

    assert breaker.record_success(state) == breaker.initial()


def test_failure_in_half_open_reopens_with_fresh_cool_down() -> None:
    breaker, clock = make_breaker(threshold=1)
    state = breaker.record_failure(breaker.initial())
    clock.advance(COOL)

    reopened = breaker.record_failure(state)

    assert reopened == BreakerState(BreakerPhase.OPEN, 2, clock.now())
    clock.advance(COOL - timedelta(seconds=1))
    assert not breaker.allow(reopened)


def test_failure_while_still_cooling_changes_nothing() -> None:
    breaker, clock = make_breaker(threshold=1)
    state = breaker.record_failure(breaker.initial())
    clock.advance(timedelta(seconds=5))

    assert breaker.record_failure(state) == state


def test_success_while_open_closes_breaker() -> None:
    breaker, _ = make_breaker(threshold=1)
    state = breaker.record_failure(breaker.initial())

    assert breaker.record_success(state) == breaker.initial()


def test_cool_down_compares_utc_instants_not_wall_clock() -> None:
    denver = ZoneInfo("America/Denver")
    opened = datetime(2026, 11, 1, 1, 30, tzinfo=denver, fold=0)  # first 01:30 (MDT)
    clock = FakeClock(datetime(2026, 11, 1, 1, 10, tzinfo=denver, fold=1))  # 01:10 MST, 40 min on
    breaker = CircuitBreaker(failure_threshold=1, cool_down=timedelta(minutes=30), clock=clock)
    state = BreakerState(BreakerPhase.OPEN, 1, opened)

    # Wall clock says 01:10 < 01:30, but 40 real minutes have passed.
    assert breaker.current(state).phase is BreakerPhase.HALF_OPEN


steps = st.one_of(
    st.just(("success", timedelta(0))),
    st.just(("failure", timedelta(0))),
    st.tuples(
        st.just("advance"),
        st.timedeltas(min_value=timedelta(0), max_value=timedelta(minutes=2)),
    ),
)


@given(
    st.integers(min_value=1, max_value=5),
    st.timedeltas(min_value=timedelta(seconds=1), max_value=timedelta(minutes=1)),
    st.lists(steps, max_size=80),
)
def test_breaker_never_half_opens_before_cool_down(
    threshold: int, cool_down: timedelta, script: list[tuple[str, timedelta]]
) -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    breaker = CircuitBreaker(failure_threshold=threshold, cool_down=cool_down, clock=clock)
    state = breaker.initial()

    for action, delta in script:
        if action == "success":
            state = breaker.record_success(state)
        elif action == "failure":
            state = breaker.record_failure(state)
        else:
            clock.advance(delta)
        seen = breaker.current(state)
        if seen.phase is BreakerPhase.HALF_OPEN:
            assert seen.opened_at is not None
            assert clock.now() - seen.opened_at >= cool_down
        if seen.phase is BreakerPhase.OPEN:
            assert seen.opened_at is not None
            assert clock.now() - seen.opened_at < cool_down
            assert not breaker.allow(state)
        if seen.phase is BreakerPhase.CLOSED:
            assert seen.failures < threshold
            assert breaker.allow(state)
