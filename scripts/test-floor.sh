#!/bin/bash
# Fails if the test count falls below the committed floor. Catches deleted suites and "no tests collected".
# Raising the floor is a human act: edit .test-floor in the commit that adds tests.
set -e
floor=$(cat .test-floor 2>/dev/null || echo 0)
count=$(bash -c "${TEST_COUNT_CMD:-mise run test:count}" 2>/dev/null | tail -1 | tr -dc '0-9')   # CI may set TEST_COUNT_CMD
[ -z "$count" ] && { echo "test-floor: could not read a test count"; exit 1; }
if [ "$count" -lt "$floor" ]; then echo "Test count $count is below floor $floor"; exit 1; fi
echo "tests: $count (floor $floor)"
