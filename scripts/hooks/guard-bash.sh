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
# UI supply chain (decision 0301): no new packages, no one-off package runners, no unfrozen install,
# and no shell writes to the approved-dependency list (the guard in scripts/ui.sh trusts that file).
# Checked per statement (split on ; & |), so a frozen install cannot vouch for another statement, and a
# flag or option between the manager and its subcommand (pnpm --dir ui add x) does not hide it.
# `pnpm install` is allowed only with both --frozen-lockfile and --ignore-scripts (mise run ui:setup).
# Known false positives: read-only commands that merely contain these words (grep "pnpm add" docs).
b='(^|[^[:alnum:]_.-])'; e='([^[:alnum:]_.-]|$)'
while IFS= read -r seg; do
  echo "$seg" | grep -Eq "${b}(pnpm|npm|yarn|bun|corepack)${e}|${b}(pnpx|npx|bunx)${e}" || continue
  if echo "$seg" | grep -Eq "${b}(pnpx|npx|bunx)${e}|${b}(npm|bun)[[:space:]]+(-[^[:space:]]+[[:space:]]+)*(exec|x)${e}|${b}(yarn|bun)${e}|${b}(add|create|init|dlx|update|up|upgrade|remove|rm|uninstall|link|patch|patch-commit|import|rebuild|approve-builds|self-update)${e}"; then
    echo "Blocked: adding, running or updating npm packages is reserved for the human (decision 0301). Ask the project manager to approve the dependency." >&2
    exit 2
  fi
  # install and its aliases (pnpm it, npm in/ins/isntall, install-test, clean-install ...)
  if echo "$seg" | grep -Eq "${b}(install|i|ci|it|cit|ic|in|ins|inst|insta|instal|isnt|isnta|isntal|isntall|install-test|install-ci-test|install-clean|clean-install|clean-install-test)${e}"; then
    # The two flags must be whole words, and no form that turns them off (=false, --no-, --config.) may appear.
    if echo "$seg" | grep -Eq "${b}npm${e}" \
       || echo "$seg" | grep -Eq -- "--(no-)?(frozen-lockfile|ignore-scripts)=|--no-(frozen-lockfile|ignore-scripts)|--config\\.|--(frozen-lockfile|ignore-scripts)=false" \
       || ! { echo "$seg" | grep -Eq -- "(^|[[:space:]])--frozen-lockfile([[:space:]]|$)" && echo "$seg" | grep -Eq -- "(^|[[:space:]])--ignore-scripts([[:space:]]|$)"; }; then
      echo "Blocked: only pnpm install --frozen-lockfile --ignore-scripts is allowed (decision 0301). Use: mise run ui:setup" >&2
      exit 2
    fi
  fi
done < <(printf '%s\n' "$cmd" | tr ';&|' '\n\n\n')
# Strip redirections to /dev/null and fd copies, then block any write-like use of the list file.
cmd_w=$(printf '%s' "$cmd" | sed -E 's/[0-9]*>&[0-9-]+//g; s/[0-9]*>>?[[:space:]]*\/dev\/null//g')
if echo "$cmd_w" | grep -q 'approved-dependencies' \
   && echo "$cmd_w" | grep -Eq ">|(^|[^[:alnum:]_.-])(tee|mv|cp|rm|ln|perl|python[0-9.]*|ruby|node|awk|ed|ex|vi|vim|nano|truncate|dd|install|patch|sponge)([^[:alnum:]_.-]|$)|sed[[:space:]]+(-[A-Za-z-]*i|--in-place)|git[[:space:]]+(apply|checkout|restore)"; then
  echo "Blocked: docs/approved-dependencies.md is edited only by the human (decision 0301). Ask the project manager to approve the dependency." >&2
  exit 2
fi
exit 0
