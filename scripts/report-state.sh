#!/usr/bin/env bash
# Print a short state report that is safe to paste to the project manager (decision 0078).
#
#   API_URL   the running api (default http://localhost:8765)
#
# It reads two api responses only, GET /v1/settings and GET /v1/events, which never carry a
# credential, and still treats them as untrusted: it prints a fixed set of fields, cuts each key's
# last-4 to 4 characters, and masks URLs, email addresses, long digit runs and token-like strings
# in every text it shows. It never reads the env file, the keychain, the secrets file or a log.
# It prints no URL, no event title and no response body. No `set -x`: that would echo the data.
set -euo pipefail

API_URL="${API_URL:-http://localhost:8765}"
API_URL="${API_URL%/}"
PAST_DAYS="${CC_REPORT_PAST_DAYS:-30}"
FUTURE_DAYS="${CC_REPORT_FUTURE_DAYS:-60}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# They go into shell arithmetic below, which would run anything that is not a plain number.
for days in "$PAST_DAYS" "$FUTURE_DAYS"; do
  if [[ ! "$days" =~ ^[0-9]+$ ]]; then
    printf 'report-state: CC_REPORT_PAST_DAYS and CC_REPORT_FUTURE_DAYS must be whole numbers\n'
    exit 2
  fi
done

for tool in curl jq; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'report-state: %s is required and was not found\n' "$tool"
    exit 2
  fi
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cc-XXXXXXXX")"
trap 'rm -rf "$WORK"' EXIT

iso_in() { # iso_in SECONDS: UTC time that many seconds from now (GNU or BSD date)
  local at=$(($(date +%s) + $1))
  date -u -d "@$at" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -r "$at" +%Y-%m-%dT%H:%M:%SZ
}

fetch() { # fetch PATH OUTPUT_FILE: succeeds only on HTTP 200
  local code
  code="$(curl -sS --max-time 15 -o "$2" -w '%{http_code}' "$API_URL$1" 2>/dev/null)" || return 1
  [[ "$code" == 200 ]]
}

commit="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [[ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null || true)" ]]; then
  commit="$commit (uncommitted changes)"
fi
version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$ROOT/pyproject.toml" 2>/dev/null | head -n 1 || true)"

echo "Command Center state report (safe to paste: no values, only status and last 4)"
printf 'time (UTC): %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'git commit: %s\n' "$commit"
printf 'app version: %s\n' "${version:-unknown}"

if ! fetch /v1/settings "$WORK/settings.json" || ! jq -e 'type == "array"' "$WORK/settings.json" >/dev/null 2>&1; then
  echo "api: not reachable, or settings were not readable"
  exit 1
fi
echo "api: reachable"

from="$(iso_in $((-PAST_DAYS * 86400)))"
to="$(iso_in $((FUTURE_DAYS * 86400)))"
noevents=no
if fetch "/v1/events?from=$from&to=$to" "$WORK/events.json" && jq -e 'type == "array"' "$WORK/events.json" >/dev/null 2>&1; then
  echo "events: counted from ${PAST_DAYS} days back to ${FUTURE_DAYS} days ahead"
else
  echo "events: not readable (counts shown as unknown)"
  echo '[]' >"$WORK/events.json"
  noevents=yes
fi

jq -r --slurpfile events "$WORK/events.json" --arg noevents "$noevents" '
  def mask:
    (. // "") | tostring
    | gsub("https?://[^\\s]+"; "[url]")
    | gsub("[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+"; "[email]")
    | gsub("(?<t>[A-Za-z0-9_./~+=-]{12,})"; if (.t | test("[0-9_-]")) then "[redacted]" else .t end)
    | gsub("[0-9]{6,}"; "[number]")
    | gsub("[\\r\\n\\t]"; " ")
    | .[0:200];
  def name: (. // "") | tostring | if test("^[a-z][a-z0-9_]{0,39}$") then . else "?" end;
  def last4: (. // "") | tostring | .[-4:] | gsub("[^A-Za-z0-9._~-]"; "?");
  def status: if . as $s | ["syncing", "ok", "reconnect", "error"] | index($s) then . else "unknown" end;
  def stamp: if (. // "" | tostring | test("^[0-9T:.+Z-]{10,40}$")) then . else "unknown" end;
  ($events[0] | map(.source // "" | tostring) | group_by(.) | map({key: .[0], value: length}) | from_entries) as $counts
  | .[]
  | ((.sync | objects) // null) as $sync
  | ((.keys | objects) // {}) as $keys
  | (.source | name) as $source
  | "",
    ( "\($source): status=\(if $sync == null then "none" else ($sync.status | status) end)"
      + (if $sync == null then "" else "  synced=\($sync.at | stamp)" end)
      + "  events=\(if $noevents == "yes" then "unknown" else ($counts[.source // "" | tostring] // 0) end)" ),
    ( if $sync != null and (($sync.message // "") != "") then "  message: \($sync.message | mask)" else empty end ),
    ( "  keys: " + (
        [ $keys | to_entries[]
          | ((.value | objects) // {}) as $v
          | "\(.key | name)=\(if ($v.set // false) == true then (if (($v.last4 // "") | tostring) == "" then "set" else "ends \($v.last4 | last4)" end) else "none" end)"
        ] | if length == 0 then "none" else join("  ") end ) )
' "$WORK/settings.json"
