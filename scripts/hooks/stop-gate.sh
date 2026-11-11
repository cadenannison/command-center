#!/bin/bash
# Runs the fast gates once per turn instead of after every edit (per-edit typecheck fires on half-finished
# multi-file changes and floods the context). Exit 2 keeps Claude working; stderr is shown to it.
# Skips when the working tree is exactly what the gate last looked at, so a read-only turn in a tree that
# is dirty for other reasons does not pay for the gates or print old failures again.
# A missing tool turns the gate off, so say so (one line on stderr, still exit 0: not a failure).
missing=""
command -v jq >/dev/null 2>&1 || missing="jq"
command -v mise >/dev/null 2>&1 || missing="${missing:+$missing and }mise"
if [ -n "$missing" ]; then
  echo "stop-gate: skipped, $missing not found on PATH, so the fast gates did not run" >&2
  exit 0
fi
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$root" || exit 0
# Loop guard: if this hook already blocked this stop once, let it through (CI is the backstop).
[ "$(jq -r '.stop_hook_active // false')" = "true" ] && exit 0
# Nothing changed at all: nothing to check.
[ -z "$(git status --porcelain 2>/dev/null)" ] && exit 0

# A fingerprint of the tree: the diff of tracked files (binary changes included; staged and unstaged
# separately when there is no commit yet) plus a hash of every untracked file.
fingerprint() {
  {
    git diff HEAD --binary 2>/dev/null || { git diff --cached --binary; git diff --binary; } 2>/dev/null
    while IFS= read -r -d '' file; do shasum "$file"; done < <(git ls-files -o --exclude-standard -z 2>/dev/null)
  } | shasum | cut -d' ' -f1
}
stamp="$(git rev-parse --git-path cc-stop-gate.sha 2>/dev/null)"
now="$(fingerprint)"
if [ -n "$stamp" ] && [ -n "$now" ] && [ "$(cat "$stamp" 2>/dev/null)" = "$now" ]; then
  exit 0
fi

# Concise ruff output: one line per finding instead of a code frame.
status=0
out=$(RUFF_OUTPUT_FORMAT=concise mise run check:fast 2>&1) || status=$?
# Record the state only after the gates finished (an interrupted run leaves no stamp and is retried), on
# a pass and on a failure alike: a red tree is reported once, and any later edit runs the gates again.
[ -n "$stamp" ] && [ -n "$now" ] && printf '%s\n' "$now" >"$stamp" 2>/dev/null
if [ "$status" -ne 0 ]; then echo "$out" | tail -60 >&2; exit 2; fi
exit 0
