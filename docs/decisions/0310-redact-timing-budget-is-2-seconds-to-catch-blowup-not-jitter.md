# 0310. The redact timing budget is 2.0 seconds, to catch blowup and not jitter

Status: accepted

Context: `test_redact_finishes_quickly_on_adversarial_input_of_200k_characters` in `tests/test_redact_gaps.py` asserted that `redact` finishes 200k adversarial characters in under 0.5 seconds. Locally, linear time at that size is about 0.12s. CI once took about 0.55s (roughly 4.5x slower than local), so the test failed on a healthy build. The test exists to catch quadratic or exponential behaviour (catastrophic regex backtracking), not small slowdowns.
Decision: Raise `_TIME_BUDGET_SECONDS` from 0.5 to 2.0. That is about 16x the local time and about 3.6x the slowest CI run seen, so runner jitter passes. A real quadratic or exponential regression at 200k characters takes many seconds to minutes, so it still fails. The comment next to the constant states this reasoning. No other line of the test file changed.
Alternative: Best of 3 runs (rejected: it triples the runtime of every adversarial case and adds a retry-like loop to the gate, which the repo rules forbid, and it hides jitter rather than setting a threshold that tolerates it). A ratio check comparing the time at N and 2N (rejected: it is more complex, and ratios of tiny timings are themselves noisy, so it would trade one flake for another). Keeping 0.5s (rejected: it is the flake).
Reason: Measured scaling is linear, and the CI slowdown is a constant factor. A fixed generous ceiling is the simplest check that separates a constant factor from an asymptotic regression.
Consequences: A regression that is only a constant factor slower (up to about 16x local) no longer fails this test. Performance at that level is not what this test guards. The test count is unchanged.
Where: `tests/test_redact_gaps.py`, `_TIME_BUDGET_SECONDS` and its comment.
Revisit when: CI exceeds 2.0s on a healthy build, or a constant-factor performance guard for `redact` is wanted (use a benchmark, not this test).
