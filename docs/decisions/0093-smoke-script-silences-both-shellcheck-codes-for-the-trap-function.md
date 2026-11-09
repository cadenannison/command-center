# 0093. The smoke script's trap function silences both shellcheck codes

Status: accepted

Context: CI's `test_shellcheck_is_clean` failed on Linux with SC2317 ("Command appears to be unreachable") on the body of `cleanup()` in `scripts/smoke-distributed.sh`. The function is only run by `trap cleanup EXIT`. The script already carried `# shellcheck disable=SC2329`, which is what shellcheck 0.11 (local) reports for a function that is never called directly. The Ubuntu shellcheck on the CI runner is older and reports the same pattern as SC2317 on each line inside the function.
Decision: The directive above `cleanup()` now reads `# shellcheck disable=SC2317,SC2329`. Each version honours the code it emits; a code the installed version does not know is ignored.
Alternative: (a) Pin or install a newer shellcheck in CI: more moving parts for one comment. (b) Drop the `trap` and call `cleanup` by hand: loses cleanup on an early exit. (c) A repo-wide `.shellcheckrc` disable: hides the warning for every script.
Reason: smallest change, scoped to the one function, correct on both shellcheck versions. The test itself is unchanged.
Where: `scripts/smoke-distributed.sh` (above `cleanup()`); tested by `tests/test_smoke_distributed_script.py::test_shellcheck_is_clean`.
Revisit when: CI's shellcheck is 0.10 or newer everywhere, then SC2317 can be dropped from the directive.
