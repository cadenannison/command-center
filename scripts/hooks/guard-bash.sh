#!/bin/bash
# Blocks git commit/push/destructive git even when wrapped (sh -c, git -C, absolute path) and --no-verify.
# Known false positives: read-only commands that merely contain these words (git log --grep commit).
command -v jq >/dev/null 2>&1 || { echo "guard-bash: jq is required; install it." >&2; exit 2; }
cmd=$(jq -r '.tool_input.command // empty')
[ -z "$cmd" ] && exit 0
if echo "$cmd" | grep -Eq 'git[^|;&]*[[:space:]](commit|push|stash|clean|rebase|restore)([[:space:]]|$)|git[^|;&]*reset[[:space:]]+--hard|git[^|;&]*checkout[[:space:]]+(--[[:space:]]|\.)|git[^|;&]*branch[[:space:]]+(-D|--delete)|--no-verify'; then
  echo "Blocked: commit, push, destructive git and --no-verify are reserved for the human. Report your changes and stop." >&2
  exit 2
fi
exit 0
