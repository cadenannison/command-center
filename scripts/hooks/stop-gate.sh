#!/bin/bash
# Runs the fast gates once per turn instead of after every edit (per-edit typecheck fires on half-finished
# multi-file changes and floods the context). Exit 2 keeps Claude working; stderr is shown to it.
command -v jq >/dev/null 2>&1 || exit 0
command -v mise >/dev/null 2>&1 || exit 0
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$root" || exit 0
# Loop guard: if this hook already blocked this stop once, let it through (CI is the backstop).
[ "$(jq -r '.stop_hook_active // false')" = "true" ] && exit 0
# Read-only turns: nothing changed, nothing to check.
[ -z "$(git status --porcelain 2>/dev/null)" ] && exit 0
out=$(mise run check:fast 2>&1) || { echo "$out" | tail -60 >&2; exit 2; }
exit 0
