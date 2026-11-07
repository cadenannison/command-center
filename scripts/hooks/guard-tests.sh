#!/bin/bash
# Existing tracked tests are read-only unless the human created .claude/allow-test-edits for this task.
# Limits: does not see Bash-driven edits (the sandbox and CI test-floor cover those) or tests inlined in source files.
command -v jq >/dev/null 2>&1 || { echo "guard-tests: jq is required; install it." >&2; exit 2; }
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
file=$(jq -r '.tool_input.file_path // empty')
[ -z "$file" ] && exit 0
rel="${file#"$root"/}"
case "$rel" in
  *.test.*|*.spec.*|*_test.go|*_test.py|test_*.py|*/test_*.py|*/tests/*|tests/*|*/test/*|test/*|*/__tests__/*|*/src/test/*) ;;
  *) exit 0 ;;
esac
[ -f "$root/.claude/allow-test-edits" ] && exit 0
if git -C "$root" cat-file -e "HEAD:$rel" 2>/dev/null; then
  echo "Blocked: $rel is an existing test. Do not edit, skip or delete tests to make them pass. If the test is wrong, stop and report why. (Human: create .claude/allow-test-edits for tasks marked 'tests: modify'.)" >&2
  exit 2
fi
exit 0
