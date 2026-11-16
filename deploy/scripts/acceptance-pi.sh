#!/usr/bin/env bash
# `make acceptance-pi` on the Mac (slice 06a-ops; D96, D236): the @pi @real_provider scenarios against planner-perf on
# the live engine. Never runs on the Pi, and only at a start time the user names (the orchestrator runs it).
#
#  1 refuse with one line when routing.env does not exist on the Pi (no engine seeded yet)
#  2 read the household user and password from the Pi's .env into this run (never printed, never in an argv)
#  3 planner-perf up with PERF_ROUTING_PROVIDER=valhalla (needs a planner with the Valhalla adapter, slice 06a),
#    ssh tunnel 127.0.0.1:18080 -> the Pi's 127.0.0.1:18080, wait for /healthz through it
#  4 uv run pytest --run-external --run-pending=slice-06a -m "pi and real_provider" on the acceptance suite
#  5 always: planner-perf stopped and removed (its volume overland_planner-perf-data stays); the user's planner and
#    its volume are never touched
# Exit non-zero when a scenario fails or planner-perf cannot be reached.
set -uo pipefail
set +x

PI_HOST=${PI_HOST:-}
PI_DIR=${PI_DIR:-}
PERF_PORT=18080
PERF_URL="http://127.0.0.1:$PERF_PORT"
WAIT_TIMEOUT=${WAIT_TIMEOUT:-180}
SUITE=tests/acceptance/overland_route_planner_mvp
# shellcheck disable=SC2016 # the $(...) is meant for the Pi's shell
PERF_COMPOSE='docker compose -p overland --profile perf --env-file .env $(test -f routing.env && echo "--env-file routing.env --profile routing") --env-file release.env'

cd "$(dirname "$0")/../.." || exit 1

say() { printf 'make acceptance-pi: %s\n' "$*" >&2; }
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
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$PI_HOST" "cd $PI_DIR && $1"
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
    { pi "$PERF_COMPOSE stop planner-perf" && pi "$PERF_COMPOSE rm -f planner-perf"; } >/dev/null ||
      say "could not remove planner-perf; run: ssh $PI_HOST 'cd $PI_DIR && $PERF_COMPOSE rm -sf planner-perf'"
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

# credentials: two lines (user, password) of the Pi's .env, kept in variables of this shell only.
credentials=$(pi '. scripts/lib.sh && env_value .env PLANNER_BASIC_AUTH_USER && env_value .env PLANNER_BASIC_AUTH_PASSWORD') ||
  die "could not read ~/$PI_DIR/.env on $PI_HOST"
newline=$'\n'
case $credentials in
  *"$newline"*) perf_user=${credentials%%"$newline"*} perf_password=${credentials#*"$newline"} ;;
  *) perf_user=$credentials perf_password= ;;
esac
credentials=

started=yes
pi "mkdir -p perf && test -f release.env && PERF_MOCK_PLAN= PERF_ROUTING_PROVIDER=valhalla $PERF_COMPOSE up -d --wait --wait-timeout $WAIT_TIMEOUT planner-perf" >/dev/null ||
  die "planner-perf did not become healthy on the live engine within $WAIT_TIMEOUT s (deploy first; needs a planner with the Valhalla adapter, slice 06a)"
ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -N -L "$PERF_PORT:127.0.0.1:$PERF_PORT" "$PI_HOST" &
tunnel=$!
reachable=
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "$PERF_URL/healthz" >/dev/null 2>&1; then
    reachable=yes
    break
  fi
  sleep 1
done
[ -n "$reachable" ] || die "planner-perf is not reachable through the tunnel at $PERF_URL"

PLANNER_PERF_URL=$PERF_URL PLANNER_PERF_USER=$perf_user PLANNER_PERF_PASSWORD=$perf_password \
  uv run pytest -q -p no:cacheprovider --run-external --run-pending=slice-06a -m "pi and real_provider" "$SUITE"
