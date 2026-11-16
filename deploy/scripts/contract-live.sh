#!/usr/bin/env bash
# `make contract-live` on the Mac (slice 06a-ops; D95, D164, D235): the recorded Valhalla answers against the live
# engine on the Pi. Never runs on the Pi, and only at a start time the user names (the orchestrator runs it).
#
#  1 refuse with one line when routing.env does not exist on the Pi (no engine seeded yet)
#  2 valhalla-tunnel up (profile ops): the Pi's 127.0.0.1:18002 -> valhalla:8002, nothing else published
#  3 ssh -L 18002:127.0.0.1:18002 from this Mac, then wait for /status through it
#  4 uv run pytest --run-external tests/contract/routing_port --valhalla-url http://127.0.0.1:18002
#  5 always: the ssh forward closed, valhalla-tunnel stopped and removed (valhalla itself is never touched)
# Exit non-zero when the checks fail or the engine cannot be reached. Layer 2 (the adapter suite) joins in slice 06a.
set -uo pipefail
set +x

PI_HOST=${PI_HOST:-}
PI_DIR=${PI_DIR:-}
TUNNEL_PORT=18002
ENGINE_URL="http://127.0.0.1:$TUNNEL_PORT"
WAIT_TIMEOUT=${WAIT_TIMEOUT:-60}
# routing.env exists (checked first): the routing profile and its env file go with the ops profile (D239).
COMPOSE='docker compose -p overland --profile ops --profile routing --env-file .env --env-file routing.env --env-file release.env'

cd "$(dirname "$0")/../.." || exit 1

say() { printf 'make contract-live: %s\n' "$*" >&2; }
die() {
  say "$*"
  exit 1
}

# The Pi's address is not in git (deploy/pi.env.example). A variable already in the environment wins over the file.
PI_ENV_FILE=${PI_ENV_FILE:-deploy/pi.env}
if [ -f "$PI_ENV_FILE" ]; then
  while IFS='=' read -r key value; do
    case $key in
      PI_HOST | PI_DIR) [ -n "${!key:-}" ] || printf -v "$key" '%s' "$value" ;;
    esac
  done <"$PI_ENV_FILE"
fi
PI_DIR=${PI_DIR:-apps/overland-planner}
[ -n "$PI_HOST" ] || die "set PI_HOST (see deploy/pi.env.example)"

pi() {
  # shellcheck disable=SC2029 # PI_DIR and the command are meant to expand on the Mac
  ssh -o BatchMode=yes "$PI_HOST" "cd $PI_DIR && $1"
}

tunnel=
started=
cleanup() {
  local status=$?
  if [ -n "$tunnel" ]; then
    kill "$tunnel" 2>/dev/null
    wait "$tunnel" 2>/dev/null
  fi
  if [ -n "$started" ]; then
    { pi "$COMPOSE stop valhalla-tunnel" && pi "$COMPOSE rm -f valhalla-tunnel"; } >/dev/null ||
      say "could not remove valhalla-tunnel; run on the Pi: $COMPOSE rm -sf valhalla-tunnel"
  fi
  exit "$status"
}
trap cleanup EXIT

pi 'test -f routing.env'
case $? in
  0) ;;
  1) die "routing.env does not exist on the Pi: run make tiles-seed first" ;;
  *) die "could not reach the Pi" ;;
esac

started=yes
pi "test -f release.env && $COMPOSE up -d --no-deps valhalla-tunnel" >/dev/null ||
  die "valhalla-tunnel did not start (deploy first: it needs release.env)"
ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -N -L "$TUNNEL_PORT:127.0.0.1:$TUNNEL_PORT" "$PI_HOST" &
tunnel=$!
reachable=
for _ in $(seq 1 "$WAIT_TIMEOUT"); do
  if curl -fsS --max-time 5 "$ENGINE_URL/status" >/dev/null 2>&1; then
    reachable=yes
    break
  fi
  sleep 1
done
[ -n "$reachable" ] || die "the engine does not answer /status through the tunnel at $ENGINE_URL"

uv run pytest -q -p no:cacheprovider --run-external tests/contract/routing_port --valhalla-url "$ENGINE_URL"
