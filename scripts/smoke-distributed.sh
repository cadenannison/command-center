#!/usr/bin/env bash
# Smoke test for a running distributed compose stack (decision 0078). The human runs it; it needs
# Docker, curl and jq. It talks to the api on loopback and restarts two containers (the weather
# worker and the normalizer). It uses the weather source only because that needs no account.
#
#   COMPOSE_ENV_FILE   the compose env file (default ~/.config/command-center/compose.env)
#   API_URL            the api (default http://localhost:8765)
#   CC_SMOKE_LAT/LON   coordinates to connect weather with (defaults: a generic city)
#   CC_SMOKE_SETTLE    seconds to wait after restarting a container (default 10)
#
# What it never does: print a credential, the coordinates, a response body or the contents of the
# env file. It never reads the env file: the file is only passed to compose by name, through dc().
# It refuses to run if weather is already connected, so it cannot overwrite or delete a real one.
set -euo pipefail

COMPOSE_ENV_FILE="${COMPOSE_ENV_FILE:-$HOME/.config/command-center/compose.env}"
API_URL="${API_URL:-http://localhost:8765}"
API_URL="${API_URL%/}"
SMOKE_LAT="${CC_SMOKE_LAT:-40.7128}"
SMOKE_LON="${CC_SMOKE_LON:--74.0060}"
SETTLE="${CC_SMOKE_SETTLE:-10}"
SYNC_LIMIT=60

FAILS=0
CONNECTED=0
DISCONNECTED=0
HTTP_CODE=000
WEATHER_COUNT=0

pass() { printf 'PASS  %s\n' "$1"; }
fail() {
  printf 'FAIL  %s\n' "$1"
  FAILS=$((FAILS + 1))
}

# Every compose call goes through here, so --env-file is on all of them.
dc() { docker compose --env-file "$COMPOSE_ENV_FILE" "$@"; }

for tool in curl jq docker; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'FAIL  %s is required and was not found\n' "$tool"
    exit 2
  fi
done
if [[ ! -f "$COMPOSE_ENV_FILE" ]]; then
  printf 'FAIL  compose env file not found (set COMPOSE_ENV_FILE)\n'
  exit 2
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cc-XXXXXXXX")"
BODY_FILE="$WORK/response.json"
REQUEST_FILE="$WORK/request.json"

# Leave nothing behind: if the script stops after connecting weather, take the connection away again.
# shellcheck disable=SC2317,SC2329  # run by the trap below; older shellcheck reports SC2317, newer SC2329
cleanup() {
  if [[ "$CONNECTED" == 1 && "$DISCONNECTED" == 0 ]]; then
    curl -sS --max-time 20 -o /dev/null -X DELETE "$API_URL/v1/settings/weather" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

# api METHOD PATH [REQUEST_FILE]: the status code lands in HTTP_CODE, the body in BODY_FILE.
api() {
  local method="$1" path="$2" request="${3:-}"
  local args=(-sS --max-time 30 -o "$BODY_FILE" -w '%{http_code}' -X "$method")
  if [[ -n "$request" ]]; then
    args+=(-H 'Content-Type: application/json' --data-binary "@$request")
  fi
  HTTP_CODE="$(curl "${args[@]}" "$API_URL$path" 2>/dev/null)" || HTTP_CODE=000
}

finish() {
  if [[ "$FAILS" -gt 0 ]]; then
    printf '\n%s step(s) FAILED\n' "$FAILS"
    exit 1
  fi
  printf '\nAll steps passed\n'
  exit 0
}

iso_in() { # iso_in SECONDS: UTC time that many seconds from now (GNU or BSD date)
  local at=$(($(date +%s) + $1))
  date -u -d "@$at" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -r "$at" +%Y-%m-%dT%H:%M:%SZ
}
FROM="$(iso_in -172800)"
TO="$(iso_in 2592000)"

weather_sync() { # the weather sync state as compact JSON, or null
  api GET /v1/settings
  [[ "$HTTP_CODE" == 200 ]] || return 1
  jq -c '[.[] | select(.source == "weather")][0].sync // null' "$BODY_FILE"
}

weather_keys_set() { # true when any weather key is stored
  api GET /v1/settings
  [[ "$HTTP_CODE" == 200 ]] || return 1
  jq '[.[] | select(.source == "weather")][0].keys // {} | [.[] | .set] | any' "$BODY_FILE"
}

count_weather() { # sets WEATHER_COUNT from the events in a wide window around today
  api GET "/v1/events?from=$FROM&to=$TO"
  [[ "$HTTP_CODE" == 200 ]] || return 1
  WEATHER_COUNT="$(jq '[.[] | select(.source == "weather")] | length' "$BODY_FILE")"
}

wait_running() { # wait_running SERVICE: up to 40 s for a running container
  local waited=0
  until [[ -n "$(dc ps --status running -q "$1" 2>/dev/null)" ]]; do
    waited=$((waited + 2))
    [[ "$waited" -le 40 ]] || return 1
    sleep 2
  done
}

restart_service() { # restart_service SERVICE: SIGKILL, start, wait until running, let it settle
  dc kill "$1" >/dev/null 2>&1 || true
  dc start "$1" >/dev/null && wait_running "$1" && sleep "$SETTLE"
}

# wait_sync_ok [AFTER_STATE_JSON]: poll until weather reports ok (and, given a previous state,
# a different one), at most SYNC_LIMIT seconds.
wait_sync_ok() {
  local previous="${1:-}" state status
  SECONDS=0
  while [[ "$SECONDS" -lt "$SYNC_LIMIT" ]]; do
    state="$(weather_sync || echo null)"
    status="$(jq -r '.status // ""' <<<"$state")"
    if [[ "$status" == ok && "$state" != "$previous" ]]; then
      return 0
    fi
    sleep 2
  done
  return 1
}

# settle_state: poll until the weather sync state has not changed for two reads in a row, so jobs
# queued earlier (the connect's and step 3's) have reported before a baseline state is taken.
settle_state() {
  local last="" state stable=0
  SECONDS=0
  while [[ "$SECONDS" -lt "$SYNC_LIMIT" ]]; do
    state="$(weather_sync || echo null)"
    if [[ "$state" == "$last" ]]; then stable=$((stable + 1)); else stable=0; fi
    last="$state"
    [[ "$stable" -ge 2 ]] && return 0
    sleep 2
  done
  return 1
}

echo "Smoke test: distributed stack at $API_URL"

# 1. api health
api GET /v1/health
if [[ "$HTTP_CODE" == 200 && "$(jq -r '.status // ""' "$BODY_FILE" 2>/dev/null)" == ok ]]; then
  pass "api health"
else
  fail "api health (HTTP $HTTP_CODE)"
  finish # nothing else can work
fi

# Guard: never touch a weather connection that was not made by this script.
if [[ "$(weather_keys_set || echo error)" != false ]]; then
  fail "weather is already connected or the settings could not be read; disconnect weather in Settings first"
  finish
fi

# 2. connect weather. The body goes in a file so the coordinates are not on a command line.
jq -n --arg lat "$SMOKE_LAT" --arg lon "$SMOKE_LON" \
  '{credentials: {latitude: $lat, longitude: $lon}}' >"$REQUEST_FILE"
api PUT /v1/settings/weather "$REQUEST_FILE"
if [[ "$HTTP_CODE" == 200 && "$(jq -r '.ok' "$BODY_FILE" 2>/dev/null)" == true ]]; then
  CONNECTED=1
  pass "connect weather"
else
  fail "connect weather (HTTP $HTTP_CODE)"
fi
rm -f "$REQUEST_FILE"
[[ "$CONNECTED" == 1 ]] || finish

# 3. sync, then wait for the normalizer to record it
api POST /v1/sync
if [[ "$HTTP_CODE" == 200 ]]; then
  pass "POST /v1/sync accepted"
else
  fail "POST /v1/sync (HTTP $HTTP_CODE)"
  finish
fi

if wait_sync_ok; then
  pass "weather reports ok within ${SYNC_LIMIT}s"
else
  fail "weather did not report ok within ${SYNC_LIMIT}s"
  finish
fi

# 4. the event count
if count_weather && [[ "$WEATHER_COUNT" -gt 0 ]]; then
  pass "weather events in the agenda: $WEATHER_COUNT"
else
  fail "no weather events in the agenda"
  finish
fi
BASELINE_COUNT="$WEATHER_COUNT"

# 5. kill the weather worker, start it, sync again: no duplicates
if ! settle_state; then
  fail "the weather sync state kept changing for ${SYNC_LIMIT}s, so the restart cannot be tested"
  finish
fi
BEFORE_STATE="$(weather_sync || echo null)"
if restart_service worker-weather; then
  pass "worker-weather killed and started"
else
  fail "worker-weather did not come back"
fi
api POST /v1/sync
if [[ "$HTTP_CODE" != 200 ]]; then
  fail "POST /v1/sync after the worker restart (HTTP $HTTP_CODE)"
elif wait_sync_ok "$BEFORE_STATE"; then
  pass "sync after the worker restart reported ok"
else
  fail "no new ok state after the worker restart within ${SYNC_LIMIT}s"
fi
if count_weather && [[ "$WEATHER_COUNT" == "$BASELINE_COUNT" ]]; then
  pass "event count unchanged after the worker restart ($WEATHER_COUNT)"
else
  fail "event count changed after the worker restart ($BASELINE_COUNT -> $WEATHER_COUNT)"
fi

# 6. kill the normalizer, start it: sync state and count unchanged. (A scheduler round landing in
# these seconds would move the state's time; the run then fails and shows both counts, so run it again.)
BEFORE_STATE="$(weather_sync || echo null)"
if restart_service normalizer; then
  pass "normalizer killed and started"
else
  fail "normalizer did not come back"
fi
AFTER_STATE="$(weather_sync || echo null)"
if [[ "$AFTER_STATE" == "$BEFORE_STATE" ]]; then
  pass "sync state unchanged after the normalizer restart"
else
  fail "sync state changed after the normalizer restart"
fi
if count_weather && [[ "$WEATHER_COUNT" == "$BASELINE_COUNT" ]]; then
  pass "event count unchanged after the normalizer restart ($WEATHER_COUNT)"
else
  fail "event count changed after the normalizer restart ($BASELINE_COUNT -> $WEATHER_COUNT)"
fi

# 7. disconnect: events and state are gone, and stay gone after a normalizer restart
api DELETE /v1/settings/weather
if [[ "$HTTP_CODE" == 200 ]]; then
  DISCONNECTED=1
  pass "disconnect weather"
else
  fail "disconnect weather (HTTP $HTTP_CODE)"
  finish
fi

gone() { # gone LABEL: no weather events, no sync state, no stored key
  local label="$1"
  if count_weather && [[ "$WEATHER_COUNT" == 0 ]]; then
    pass "weather events gone $label"
  else
    fail "weather events remain $label ($WEATHER_COUNT)"
  fi
  if [[ "$(weather_sync || echo error)" == null ]]; then
    pass "weather sync state gone $label"
  else
    fail "weather sync state remains $label"
  fi
  if [[ "$(weather_keys_set || echo error)" == false ]]; then
    pass "weather keys gone $label"
  else
    fail "weather keys remain, or could not be read, $label"
  fi
}
gone "after the disconnect"
if restart_service normalizer; then
  pass "normalizer killed and started again"
else
  fail "normalizer did not come back"
fi
gone "after a normalizer restart"

finish
