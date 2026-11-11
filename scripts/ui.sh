#!/bin/bash
# UI gates (decisions 0300, 0301, 0303). Usage: scripts/ui.sh guard|setup|test|count|floor|fast|check|audit
# Every subcommand skips with a notice (exit 0) until ui/package.json exists, so the gates can be wired
# into `mise run check` and CI before the UI is scaffolded. The repo root is always this script's parent.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
ui="$root/ui"
cmd="${1:-}"
fail() { echo "ui: $*" >&2; exit 1; }

case "$cmd" in
  guard|setup|test|count|floor|fast|check|audit) ;;
  *) fail "usage: scripts/ui.sh guard|setup|test|count|floor|fast|check|audit" ;;
esac
if [ ! -f "$ui/package.json" ]; then echo "ui: no ui/package.json yet, skipping $cmd"; exit 0; fi

pnpm_in_ui() {
  command -v pnpm >/dev/null 2>&1 || fail "pnpm not found on PATH (it comes from mise.toml); run: mise install"
  (cd "$ui" && pnpm "$@")
}

# Decision 0301: pinned pnpm, exact versions, approved names, install scripts off, release age.
# The approved names come from docs/approved-dependencies.md (human-edited; see that file for the format).
guard() {
  command -v jq >/dev/null 2>&1 || fail "jq is required"
  local listfile="$root/docs/approved-dependencies.md" pkg="$ui/package.json" bad=0 approved_names
  [ -f "$listfile" ] || fail "docs/approved-dependencies.md (the approved-dependency list) is missing"
  # Only a line that starts with "- " and a backticked name approves that name; prose approves nothing.
  approved_names=$(sed -nE 's/^- `([^`]+)`.*/\1/p' "$listfile")
  [ -n "$approved_names" ] || fail "docs/approved-dependencies.md has no entry lines (- \`name\`)"
  problem() { echo "ui guard: $*" >&2; bad=1; }
  jq -e 'type == "object"' "$pkg" >/dev/null 2>&1 || fail "ui/package.json is not a JSON object"

  # 1. packageManager is pnpm with an exact version and hash, and equals the pnpm pinned in mise.toml.
  local pm pm_ver="" mise_ver
  pm=$(jq -r '.packageManager // empty' "$pkg")
  if [[ "$pm" =~ ^pnpm@([0-9]+\.[0-9]+\.[0-9]+)\+sha512\.[0-9a-f]+$ ]]; then pm_ver="${BASH_REMATCH[1]}"
  else problem "packageManager must be pnpm@X.Y.Z+sha512.<hash> (got '${pm:-none}')"; fi
  mise_ver=$(sed -nE 's/^pnpm[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "$root/mise.toml" | head -1)
  if [ -z "$mise_ver" ]; then problem "mise.toml does not pin pnpm"
  elif [ -n "$pm_ver" ] && [ "$pm_ver" != "$mise_ver" ]; then
    problem "packageManager pnpm $pm_ver differs from mise.toml pnpm $mise_ver"
  fi

  # 2. The lockfile is committed. This is the only package.json (a second one would be a second,
  #    unchecked dependency set), and nothing above ui/ turns the repo root into a pnpm workspace.
  [ -f "$ui/pnpm-lock.yaml" ] || problem "ui/pnpm-lock.yaml is missing"
  local extra
  extra=$(find "$ui" -name node_modules -prune -o -name package.json -not -path "$ui/package.json" -print | head -1)
  [ -z "$extra" ] || problem "only ui/package.json is allowed; found ${extra#"$root"/}"
  for f in "$root/pnpm-workspace.yaml" "$root/.npmrc"; do
    [ -e "$f" ] && problem "${f#"$root"/} would apply to ui/ installs and is not checked; remove it"
  done

  # 3. Policy settings (.npmrc or pnpm-workspace.yaml): scripts off, exact pins, release age >= 7 days.
  #    Every assignment of a key must be safe, not only the last: which file pnpm 11 reads first for each
  #    key is confirmed by the scaffold task (decision 0301), so a safe value in one file must not hide an
  #    unsafe one in the other.
  local cfg="" f v
  for f in "$ui/.npmrc" "$ui/pnpm-workspace.yaml"; do [ -f "$f" ] && cfg+=$(cat "$f")$'\n'; done
  vals() { sed -nE "s/^[[:space:]]*[\"']?($1)[\"']?[[:space:]]*[=:][[:space:]]*[\"']?([^\"'#[:space:]]+).*/\2/p" <<<"$cfg"; }
  # A YAML flow mapping ({a: b}) hides keys from the line-based checks below, so it is not allowed.
  grep -Eq '^[[:space:]]*\{' <<<"$cfg" && problem "a flow mapping ({...}) is not allowed in ui/.npmrc or ui/pnpm-workspace.yaml; use one key per line"
  need_true() {   # $1 = key pattern, $2 = label
    local seen=0
    while IFS= read -r v; do seen=1; [ "$v" = true ] || problem "$2 must be true everywhere it is set (got '$v')"; done < <(vals "$1")
    [ "$seen" -eq 1 ] || problem "$2 must be set to true in ui/.npmrc or ui/pnpm-workspace.yaml"
  }
  need_true 'ignore-scripts|ignoreScripts' "ignore-scripts"
  need_true 'save-exact|saveExact' "save-exact"
  local seen_age=0
  while IFS= read -r v; do
    seen_age=1
    { [[ "$v" =~ ^[0-9]+$ ]] && [ "$v" -ge 10080 ]; } || problem "minimumReleaseAge must be at least 10080 minutes everywhere it is set (got '$v')"
  done < <(vals 'minimum-release-age|minimumReleaseAge')
  [ "$seen_age" -eq 1 ] || problem "minimumReleaseAge must be set to at least 10080 minutes"
  if grep -Ei '^[[:space:]]*["'"'"']?(minimum-release-age-exclude|minimumReleaseAgeExclude)' <<<"$cfg" | grep -Evq '\[\][[:space:]]*$'; then
    problem "minimumReleaseAgeExclude must stay empty"
  fi

  # Code, rewrites, other registries or other package sets that apply at install time, even with
  # --ignore-scripts, need a decision. A line starting with // is a registry credential (never in the repo).
  ls "$ui"/.pnpmfile.* >/dev/null 2>&1 && problem "a .pnpmfile runs code at install time and is not allowed"
  if grep -Eqi '^[[:space:]]*["'"'"']?((global-)?pnpmfile|overrides|packageExtensions|patchedDependencies|onlyBuiltDependencies|allowBuilds|neverBuiltDependencies|ignoredBuiltDependencies|dangerously-?allow-?all-?builds|auditConfig|packages|catalogs?|configDependencies|onlyBuiltDependenciesFile|useNodeVersion|nodeVersion|executionEnv|pnpmfileChecksum|(@[^:=[:space:]]+:)?registry|strict-?ssl|_auth[A-Za-z]*)["'"'"']?[[:space:]]*[:=]|^[[:space:]]*//' <<<"$cfg"; then
    problem "pnpmfile, overrides, packageExtensions, patchedDependencies, build lists, auditConfig, workspace packages, catalogs, configDependencies, runtime downloads, registries, strict-ssl and credentials are not allowed in ui/.npmrc or ui/pnpm-workspace.yaml without a decision"
  fi

  # 4. No overrides; no runtime download; the only pnpm key is the build allow-list; every dependency
  #    name approved in the file; every version exact.
  jq -e '((.overrides // {}) == {}) and ((.resolutions // {}) == {})
         and (((.pnpm // {}) | type == "object") and ((.pnpm // {}) | keys | all(. == "onlyBuiltDependencies")))
         and ((.devEngines // {}) | (type == "object") and (.runtime // null) == null)
         and ((.engines // {}) | (type == "object") and (.runtime // null) == null)' "$pkg" >/dev/null \
    || problem "overrides, resolutions, runtime downloads (devEngines/engines runtime) and any pnpm key other than onlyBuiltDependencies are not allowed without a decision"
  approved() {   # approved when a line lists the name exactly, or lists its scope as `@scope/*`
    local n="$1"
    [[ "$n" =~ ^(@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*$ ]] || return 1
    grep -qxF -- "$n" <<<"$approved_names" && return 0
    case "$n" in @*/*) grep -qxF -- "${n%%/*}/*" <<<"$approved_names" && return 0 ;; esac
    return 1
  }
  local name spec deps builds
  # Read into variables first so a manifest jq cannot parse fails the guard instead of listing nothing.
  deps=$(jq -r '[.dependencies, .devDependencies, .optionalDependencies, .peerDependencies] | map(. // {}) | add // {} | to_entries[] | "\(.key)\t\(.value)"' "$pkg") \
    || { problem "ui/package.json dependency sections are not objects of name to version"; deps=""; }
  while IFS=$'\t' read -r name spec; do
    [ -n "$name" ] || continue
    approved "$name" || problem "dependency '$name' is not on docs/approved-dependencies.md (needs project manager approval)"
    [[ "$spec" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || problem "dependency '$name' version '$spec' is not an exact version"
  done <<<"$deps"
  builds=$(jq -r '((.pnpm // {}).onlyBuiltDependencies // [])[]' "$pkg") \
    || { problem "pnpm.onlyBuiltDependencies must be a list of names"; builds=""; }
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    approved "$name" || problem "build allow-list entry '$name' is not on docs/approved-dependencies.md"
  done <<<"$builds"
  [ "$bad" -eq 0 ] || exit 1
  echo "ui guard: ok"
}

# Decision 0303: the UI's own test floor. `count` runs Vitest with the JSON reporter and prints the total.
count() {
  local out n
  out=$(mktemp "${TMPDIR:-/tmp}/ui-count.XXXXXX")
  pnpm_in_ui exec vitest run --reporter=json --outputFile="$out" >/dev/null 2>&1 || true
  n=$(jq -r '.numTotalTests // empty' "$out" 2>/dev/null || true)
  rm -f "$out"
  [ -n "$n" ] || fail "could not read a test count from vitest"
  echo "$n"
}
floor() {
  local want n
  want=$(tr -dc '0-9' <"$ui/.test-floor" 2>/dev/null || true)
  [ -n "$want" ] || fail "ui/.test-floor is missing or not a number"
  n=$(count | tail -1 | tr -dc '0-9')
  [ -n "$n" ] || fail "could not read a test count"
  [ "$n" -ge "$want" ] || fail "test count $n is below ui/.test-floor $want"
  echo "ui tests: $n (floor $want)"
}

case "$cmd" in
  guard) guard ;;
  setup) guard; pnpm_in_ui install --frozen-lockfile --ignore-scripts ;;
  test) pnpm_in_ui run test ;;
  count) count ;;
  floor) floor ;;
  fast) guard; pnpm_in_ui run typecheck; pnpm_in_ui run lint ;;
  check) guard; pnpm_in_ui run typecheck; pnpm_in_ui run lint; pnpm_in_ui run test; floor; pnpm_in_ui run build ;;
  audit)   # advisory: production advisories at high or above fail; dev-tool advisories are reported only
    pnpm_in_ui audit --prod --audit-level high
    pnpm_in_ui audit --dev --audit-level high || echo "ui: dev-dependency advisories found (reported, not failing)" >&2 ;;
esac
