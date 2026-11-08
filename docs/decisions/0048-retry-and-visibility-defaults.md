# 0048. Retry and visibility-timeout defaults

Status: accepted

Context: `RetryPolicy` and the visibility timeout need defaults that suit a personal dashboard syncing Canvas, calendars, Gmail and weather.
Decision:
- `DEFAULT_RETRY_POLICY`: 5 attempts, 5 s base delay, factor 2, cap 5 minutes. `attempt` is 1-based; the wait after attempt n is `E(n-1) + rng * (E(n) - E(n-1))` with `E(n) = min(cap, base * factor^(n-1))`, `E(0) = E(1)`; the wait after attempt 1 is exactly the base delay. This spreads retries ("jitter") yet never exceeds the cap and never decreases as attempts grow, whatever the random draws.
- `DEFAULT_VISIBILITY_TIMEOUT`: 5 minutes. The largest sync (Gmail, 20 pages of threads, or Canvas with many courses) is expected to finish well inside that.
- A redelivery after the visibility timeout counts as an attempt. A job whose attempts are used up and whose last delivery times out is dead-lettered, so a job that crashes its worker cannot loop forever.
- Both are constructor arguments of the queues; no setting exists yet.
- Validation choices in `core/resilience.py`: `RetryPolicy.delay` raises `ValueError` when the Rng returns a value outside [0, 1) instead of clamping, so a broken Rng is noticed; `BreakerState` rejects negative failures, a naive `opened_at`, and an open or half-open phase without `opened_at`; a float overflow in `factor**n` clamps to the cap. The circuit breaker is a primitive only: no queue or service uses it yet.
Alternative: full jitter (`rng * E(n)`), which spreads best but can shorten the wait as attempts grow and so breaks the "never decreases" property; a short timeout (30 s) with heartbeats; redeliveries that do not count.
Reason: Interval jitter gives monotone, capped waits with a provable property test. Heartbeats are more machinery than a personal app needs. Uncounted redeliveries make a poison job immortal.
Where: `src/command_center/core/resilience.py`, `adapters/inprocess_queue.py`, `adapters/queue_redis.py`.
Revisit when: a sync is measured near five minutes, defaults need to be user-tunable (add `Settings` fields read by the composition roots), or retries cluster visibly.
