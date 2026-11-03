#!/usr/bin/env bash
# Functional smoke of the arm64 planner image (DEVOPS job 6, step 01-08): runs it as on the Pi (--init, 1 GB limit,
# named volume on /data, offline mock road map) and checks /healthz, the solver and data folder probes in /api/health
# (file_store, mount_table, data_dir: the volume is persistent, D121) and the
# aarch64 OR-Tools wheel. Under QEMU the OR-Tools probe child is slow (probe timeout 30 s) and /healthz answers only
# after the start-up probes, hence 180 s; a native arm64 runner passes 60. No timing or RSS figures under QEMU.
#
# Usage: image-smoke.sh IMAGE [TIMEOUT_SECONDS]
set -euo pipefail

image="${1:?usage: image-smoke.sh IMAGE [TIMEOUT_SECONDS]}"
timeout_s="${2:-180}"
port="${SMOKE_PORT:-18080}"
container="overland-smoke-$$"
volume="overland-smoke"
base="http://127.0.0.1:${port}"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
  echo "image-smoke: FAIL: $*" >&2
  echo "----- docker logs ${container} -----" >&2
  docker logs "$container" >&2 2>&1 || echo "(no container logs)" >&2
  exit 1
}

docker volume create "$volume" >/dev/null
docker run --detach --name "$container" \
  --platform linux/arm64 --init -m 1g \
  -e ROUTING_PROVIDER=mock \
  -v "${volume}:/data" \
  -p "127.0.0.1:${port}:8080" \
  "$image" >/dev/null || fail "docker run ${image} failed"

echo "image-smoke: waiting up to ${timeout_s} s for ${base}/healthz"
deadline=$((SECONDS + timeout_s))
healthz=""
until healthz="$(curl -fsS --max-time 5 "${base}/healthz" 2>/dev/null)"; do
  if [ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]; then
    fail "the container stopped before /healthz answered"
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    fail "/healthz did not answer within ${timeout_s} s"
  fi
  sleep 3
done
case "$healthz" in
  *'"status":"ok"'*) echo "image-smoke: /healthz ok" ;;
  *) fail "/healthz answered ${healthz}" ;;
esac

health="$(curl -fsS --max-time 10 "${base}/api/health")" || fail "/api/health did not answer"
# The named volume on /data is a persistent disk: the data folder probes (step 03-02, D121) must all report ok.
for component in tour_solver file_store mount_table data_dir; do
  outcome="$(printf '%s' "$health" | python3 -c 'import json, sys; print(json.load(sys.stdin)["components"][sys.argv[1]]["outcome"])' "$component")" \
    || fail "/api/health has no ${component} component: ${health}"
  if [ "$outcome" != "ok" ]; then
    fail "${component} probe outcome is ${outcome}: ${health}"
  fi
  echo "image-smoke: /api/health ${component} ok"
done

docker exec "$container" python -c 'import ortools' || fail "import ortools failed inside the image"
echo "image-smoke: import ortools ok"
echo "image-smoke: PASS"
