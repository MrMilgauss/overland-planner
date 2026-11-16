#!/usr/bin/env bash
# `make perf-pi [N=10] [ITEMS=60] [POINTS=] [MODE=e2e]` on the Mac (slice 03-ops; D96, D135, D146, D147, D164, D175, D177).
# Never runs on the Pi, and only at a start time the user names (the orchestrator runs it, never the crafter).
#
#  1 read the household user and password from the Pi's .env into this run (never printed, never in an argv)
#  2 planner-perf up with the deployed digest (release.env), profile perf, on 127.0.0.1:18080 of the Pi only
#  3 ssh tunnel 127.0.0.1:18080 -> the Pi's 127.0.0.1:18080 (PLANNER_PERF_URL)
#  4 golden order of I1; I2's road map copied to ./perf and planner-perf restarted with it; golden order of I2;
#    restarted without it. A mismatch stops here: nothing is measured.
#  5 N=10 ITEMS=60 POINTS= (the K5 gate): the two @pi scenarios of slice 03 (warm-up, 10 measured runs, reference);
#    any other mode: tests/perf/perf_pi.py measure (warm-up, N measured runs) of the generated I1 variant
#  6 the report (every run's state and stage_ms, slowest, nearest-rank p95) in .data/perf/<timestamp>.json
#  7 always: planner-perf stopped and removed (its volume overland_planner-perf-data stays); the user's planner and
#    its volume are never touched
# MODE=e2e (D236; needs a planner with the Valhalla adapter, slice 06a, and routing.env on the Pi): after step 4,
#  5e planner-perf restarted with PERF_ROUTING_PROVIDER=valhalla, the 60-item I1 seeded once; then N cold runs: each
#     one recreates planner-perf first (its in-memory legs are forgotten), presses Calculate with ignore_memo and
#     ends when the stored plan is read back (or the geometry answer arrives, slice 09)
#  6e the report (every run, slowest e2e and solve, retried and heavy-second-pass counts) in .data/perf/<timestamp>.json
# Exit non-zero on any golden mismatch, failed run or missed gate.
set -uo pipefail
set +x

PI_HOST=${PI_HOST:-}
PI_DIR=${PI_DIR:-}
N=${N:-10}
ITEMS=${ITEMS:-60}
POINTS=${POINTS:-}
MODE=${MODE:-}
PERF_OUT_DIR=${PERF_OUT_DIR:-.data/perf}
PERF_PORT=18080
PERF_URL="http://127.0.0.1:$PERF_PORT"
I2_ROAD_MAP=tests/acceptance/overland_route_planner_mvp/fixtures/golden/i2-sparse.road-map.yaml
I2_MOCK_PLAN=/perf/i2-sparse.road-map.yaml
SCENARIOS=tests/acceptance/overland_route_planner_mvp/test_slice_03.py
WAIT_TIMEOUT=180
# The remote shell adds routing.env and the routing profile when the file exists (D239): planner-perf joins that network.
# shellcheck disable=SC2016 # the $(...) is meant for the Pi's shell
PERF_COMPOSE='docker compose -p overland --profile perf --env-file .env $(test -f routing.env && echo "--env-file routing.env --profile routing") --env-file release.env'

cd "$(dirname "$0")/../.." || exit 1

say() { printf 'make perf-pi: %s\n' "$*" >&2; }
die() {
  say "$*"
  exit 1
}

# The Pi's address is not in git (deploy/pi.env.example). A variable already in the environment wins over the file.
PI_ENV_FILE=${PI_ENV_FILE:-deploy/pi.env}
if [ -f "$PI_ENV_FILE" ]; then
  while IFS='=' read -r key value; do
    case $key in
      PI_HOST | PI_DIR | PLANNER_URL) [ -n "${!key:-}" ] || printf -v "$key" '%s' "$value" ;;
    esac
  done <"$PI_ENV_FILE"
fi
PI_DIR=${PI_DIR:-apps/overland-planner}
[ -n "$PI_HOST" ] || die "set PI_HOST (see deploy/pi.env.example)"

whole_number() { case $1 in '' | *[!0-9]* | 0*) return 1 ;; esac; }
case $MODE in
  '' | e2e) ;;
  *) die "MODE must be empty or e2e, not '$MODE'" ;;
esac
whole_number "$N" || die "N must be a positive whole number, not '$N'"
whole_number "$ITEMS" || die "ITEMS must be a positive whole number, not '$ITEMS'"
[ -z "$POINTS" ] || whole_number "$POINTS" || die "POINTS must be empty or a positive whole number, not '$POINTS'"

pi() {
  # shellcheck disable=SC2029 # PI_DIR and the command are meant to expand on the Mac
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$PI_HOST" "cd $PI_DIR && $1"
}

# perf_up MOCK_PLAN [valhalla [recreate]]: (re)create planner-perf; an empty MOCK_PLAN is the default road map (I1, the
# measurement). `valhalla` points it at the live engine (PERF_ROUTING_PROVIDER, D236); `recreate` forces a new container.
perf_up() {
  local provider=${2:+ PERF_ROUTING_PROVIDER=valhalla} recreate=${3:+ --force-recreate}
  pi "mkdir -p perf && test -f release.env && PERF_MOCK_PLAN=$1$provider $PERF_COMPOSE up -d$recreate --wait --wait-timeout $WAIT_TIMEOUT planner-perf"
}

perf_down() {
  pi "$PERF_COMPOSE stop planner-perf"
  pi "$PERF_COMPOSE rm -f planner-perf"
}

work=$(mktemp -d)
tunnel=
started=
cleanup() {
  local status=$?
  if [ -n "$tunnel" ]; then
    kill "$tunnel" 2>/dev/null
    wait "$tunnel" 2>/dev/null
  fi
  if [ -n "$started" ]; then
    perf_down || say "could not take planner-perf down; run: ssh $PI_HOST 'cd $PI_DIR && $PERF_COMPOSE rm -sf planner-perf'"
  fi
  rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT

# e2e needs the engine: refuse before anything starts when no tileset was seeded (routing.env, make tiles-seed)
if [ "$MODE" = e2e ]; then
  pi 'test -f routing.env'
  case $? in
    0) ;;
    1) die "routing.env does not exist on the Pi: run make tiles-seed first" ;;
    *) die "could not reach the Pi" ;;
  esac
fi

# 1 credentials: two lines (user, password) of the Pi's .env, kept in variables of this shell only.
credentials=$(pi '. scripts/lib.sh && env_value .env PLANNER_BASIC_AUTH_USER && env_value .env PLANNER_BASIC_AUTH_PASSWORD') ||
  die "could not read ~/$PI_DIR/.env on $PI_HOST"
newline=$'\n'
case $credentials in
  *"$newline"*) perf_user=${credentials%%"$newline"*} perf_password=${credentials#*"$newline"} ;;
  *) perf_user=$credentials perf_password= ;;
esac
credentials=

# on_planner_perf COMMAND...: COMMAND with the tunnel URL and the credentials in its environment (not its argv).
on_planner_perf() {
  PLANNER_PERF_URL=$PERF_URL PLANNER_PERF_USER=$perf_user PLANNER_PERF_PASSWORD=$perf_password "$@"
}

golden() {
  say "golden order of $1 on planner-perf"
  GOLDEN_INSTANCE=$1 on_planner_perf uv run pytest -q -p no:cacheprovider -m golden_order tests/golden ||
    die "the golden order of $1 differs on planner-perf (or its check failed): nothing measured"
}

# 2-3 planner-perf and the tunnel
started=yes
perf_up "" || die "planner-perf did not become healthy within $WAIT_TIMEOUT s (deploy first: it runs release.env's digest)"
ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -N -L "$PERF_PORT:127.0.0.1:$PERF_PORT" "$PI_HOST" &
tunnel=$!
wait_reachable() {
  local _
  for _ in $(seq 1 30); do
    curl -fsS --max-time 5 "$PERF_URL/healthz" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}
wait_reachable || die "planner-perf is not reachable through the tunnel at $PERF_URL"

# 4 golden orders (D175): I1 on the default road map, I2 on its own
golden i1
rsync -a "$I2_ROAD_MAP" "$PI_HOST:$PI_DIR/perf/" || die "could not copy I2's road map to the Pi"
perf_up "$I2_MOCK_PLAN" || die "planner-perf did not restart with I2's road map"
golden i2
perf_up "" || die "planner-perf did not restart on the default road map"

# 5-6 the measurement and its report
mkdir -p "$PERF_OUT_DIR"
report="$PERF_OUT_DIR/$(date -u +%Y%m%dT%H%M%SZ).json"
if [ "$MODE" = e2e ]; then
  # 5e-6e cold end-to-end runs on the live engine (D236): the project is seeded once, planner-perf recreated before each run
  perf_up "" valhalla || die "planner-perf did not restart on the live engine (needs a planner with the Valhalla adapter, slice 06a)"
  wait_reachable || die "planner-perf is not reachable through the tunnel at $PERF_URL"
  project="$work/project"
  runs="$work/e2e-runs.jsonl"
  : >"$runs"
  on_planner_perf uv run python -m tests.perf.perf_pi e2e-seed --items "$ITEMS" --project-file "$project" ||
    die "could not seed the $ITEMS-item project on planner-perf"
  broken=
  for number in $(seq 1 "$N"); do
    say "cold run $number of $N"
    perf_up "" valhalla recreate || {
      broken="planner-perf did not restart for run $number"
      break
    }
    wait_reachable || {
      broken="planner-perf is not reachable through the tunnel for run $number"
      break
    }
    on_planner_perf uv run python -m tests.perf.perf_pi e2e-run --project-file "$project" --out "$runs" || {
      broken="run $number could not be measured"
      break
    }
  done
  verdict=0
  uv run python -m tests.perf.perf_pi e2e-report --runs "$runs" --n "$N" --items "$ITEMS" --out "$report" || verdict=$?
  [ -z "$broken" ] || die "$broken; report: $report"
  [ "$verdict" -eq 0 ] || die "the e2e gate is missed or a run did not finish; report: $report"
elif [ "$N" = 10 ] && [ "$ITEMS" = 60 ] && [ -z "$POINTS" ]; then
  runs="$work/runs.jsonl"
  : >"$runs"
  scenarios=0
  PERF_REPORT=$runs on_planner_perf uv run pytest -q -p no:cacheprovider --run-external --run-pending=slice-03 -m pi \
    "$SCENARIOS" || scenarios=$?
  verdict=0
  uv run python -m tests.perf.perf_pi report --runs "$runs" --n "$N" --items "$ITEMS" --out "$report" || verdict=$?
  [ "$scenarios" -eq 0 ] || die "the @pi scenarios of slice 03 failed (exit $scenarios); report: $report"
  [ "$verdict" -eq 0 ] || die "the K5 gate is missed or a run did not finish; report: $report"
else
  if [ -n "$POINTS" ]; then set -- --points "$POINTS"; else set --; fi
  on_planner_perf uv run python -m tests.perf.perf_pi measure --n "$N" --items "$ITEMS" "$@" --out "$report" ||
    die "a measured run did not finish or the gate is missed; report: $report"
fi
say "report: $report"
