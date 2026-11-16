#!/usr/bin/env bash
# Quarterly map-data refresh of the Valhalla tileset (D83, D92, D166, D237, D239, D240; ADR-013 Amendment 3). Run by
# `make tiles-refresh`, at a start time the owner names (about 40 minutes without routing):
#
#   cd ~/apps/overland-planner && bash scripts/tiles-refresh.sh
#
#  1 preflight, read-only: routing.env exists (make tiles-seed came first); the new tileset is named by the UTC date and
#    is neither served (routing.env), kept for rollback (routing.env.prev) nor already in the volume; disk free >= 25 GB;
#    MemAvailable >= build cap + 1 GiB; the planner's /api/diagnostics is asked (a note when it does not answer)
#  2 while valhalla serves: valhalla-fetch downloads the five Geofabrik extracts into build/src and merges them into
#    build/alps.osm.pbf (MemAvailable >= 7 GiB checked again just before the merge); the extracts are deleted
#  3 valhalla stopped, valhalla-build makes the tiles under its cap, the deltas of valhalla/valhalla.overrides.json are
#    applied to the built valhalla.json with jq inside the Valhalla image
#  4 promote to tilesets/<YYYYMMDD>/ (with SHA256SUMS), build/ deleted; routing.env -> routing.env.prev, new pointer,
#    valhalla started and waited for, /status read (version 3.9.1)
#  5 only then: every tileset but the new and the previous one is deleted; tiles.log gets `ok`
# Any failure before 4 starts valhalla again on the old tileset (routing.env untouched); a failed switch restores
# routing.env and .prev, starts the old tileset and keeps the new directory for inspection. One tiles.log line per run.
# The planner is never touched. Seams for the offline tests: TILES_DATE (the UTC date), MEMINFO (/proc/meminfo),
# DOCKER_ROOT (the disk checked).
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
# shellcheck source=deploy/scripts/lib.sh disable=SC1091 # followed by make lint-ci; the pre-commit hook gets no -x
. scripts/lib.sh

NEW=${TILES_DATE:-$(date -u +%Y%m%d)}
GEOFABRIK=https://download.geofabrik.de
EXTRACTS=(europe/italy-latest europe/switzerland-latest europe/austria-latest europe/france/rhone-alpes-latest
  europe/france/provence-alpes-cote-d-azur-latest)
MIN_FREE_KB=$((25 * 1024 * 1024))
MERGE_MIN_KB=$((7 * 1024 * 1024))
MODIFIED=

record() { append_tiles_log refresh "$NEW" "$MODIFIED" "$1" "${2:-}"; }

# refuse WHY: a preflight refusal, nothing was changed.
refuse() {
  say "tiles-refresh: $1"
  record failed "$1"
  exit 1
}

# fail_stage STAGE WHY: the old tileset keeps (or gets back) the serving; routing.env was never touched.
fail_stage() {
  say "tiles-refresh: $2; starting valhalla on the old tileset again"
  planner_compose up -d valhalla >&2 || say "tiles-refresh: the old valhalla did not start either"
  record failed "refresh failed ($1)"
  exit 1
}

# undo_switch WHY: pointers back as they were, valhalla on the old tileset, the new directory stays for inspection.
undo_switch() {
  say "tiles-refresh: $1; restoring routing.env, tilesets/$NEW is kept for inspection"
  restore_routing
  planner_compose up -d valhalla >&2 || say "tiles-refresh: the old valhalla did not start either"
  record failed "refresh failed (switch)"
  exit 1
}

mem_available_kb() { awk '$1 == "MemAvailable:" { print $2 }' "${MEMINFO:-/proc/meminfo}" 2>/dev/null; }

# build_cap_kb: the valhalla-build memory cap (VALHALLA_BUILD_MEM like compose reads it, default 9g) in KiB.
build_cap_kb() {
  local cap n=
  cap=${VALHALLA_BUILD_MEM:-$(env_value .env VALHALLA_BUILD_MEM)}
  cap=${cap:-9g}
  case $cap in
    *[gG]) n=${cap%?} && echo $((n * 1024 * 1024)) ;;
    *[mM]) n=${cap%?} && echo $((n * 1024)) ;;
  esac
  case $n in '' | *[!0-9]*) return 1 ;; esac
}

# 1. Preflight.
exec 9>>.deploy.lock
flock -n 9 || refuse "a deploy, rollback or tiles run is already running"
current=$(env_value routing.env VALHALLA_TILESET)
previous=$(env_value routing.env.prev VALHALLA_TILESET)
[ -n "$current" ] || refuse "no routing.env: nothing is served yet, run make tiles-seed first"
case $NEW in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) refuse "the new tileset name must be 8 digits (YYYYMMDD), got '$NEW'" ;;
esac
if [ "$NEW" = "$current" ] || [ "$NEW" = "$previous" ]; then
  refuse "tileset $NEW is served or kept for rollback; a served or rollback tileset is not overwritten"
fi
# shellcheck disable=SC2016 # $1 is expanded by the container's sh
if docker run --rm --network none -v "$VALHALLA_VOLUME:/vol:ro" "$SNAPSHOT_IMAGE" \
  sh -c 'test -d "/vol/$1"' tileset-exists "tilesets/$NEW" >/dev/null 2>&1; then
  refuse "tilesets/$NEW already exists; one refresh a day at most, nothing is overwritten"
fi
root=${DOCKER_ROOT:-/var/lib/docker}
[ -d "$root" ] || root=$HOME
free_kb=$(df -Pk "$root" 2>/dev/null | awk 'NR == 2 { print $4 }')
if [ "${free_kb:-0}" -lt "$MIN_FREE_KB" ]; then
  refuse "disk: only $((${free_kb:-0} / 1024 / 1024)) GB free (need 25 GB)"
fi
cap_kb=$(build_cap_kb) || refuse "VALHALLA_BUILD_MEM is not a size like 9g"
need_kb=$((cap_kb + 1024 * 1024))
available_kb=$(mem_available_kb)
if [ "${available_kb:-0}" -lt "$need_kb" ]; then
  refuse "MemAvailable: $((${available_kb:-0} / 1024 / 1024)) GB, need $((need_kb / 1024 / 1024)) GB (build cap + 1 GiB)"
fi
if ! curl_planner "http://$(env_value .env PLANNER_BIND):$(planner_port)/api/diagnostics" >/dev/null 2>&1; then
  say "tiles-refresh: note: the planner's /api/diagnostics did not answer; carrying on"
fi

# 2. Download and merge while valhalla serves.
say "tiles-refresh: tileset $NEW; downloading and merging while the old tileset serves"
# shellcheck disable=SC2016 # the script is expanded by the container's sh
docker run --rm --network none -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
  sh -c 'rm -rf /vol/build && mkdir -p /vol/build/src' prepare-build >&2 ||
  fail_stage download "cannot prepare build/ in the volume"
urls=()
for extract in "${EXTRACTS[@]}"; do urls+=("$GEOFABRIK/$extract.osm.pbf"); done
# shellcheck disable=SC2016 # the script is expanded by the container's sh
planner_compose --profile valhalla-build run --rm -T valhalla-fetch sh -c 'set -e
  apt-get update -qq && apt-get install -y -qq --no-install-recommends curl ca-certificates
  cd /work/src
  for url in "$@"; do echo "tiles-refresh: downloading $url" >&2; curl -fL --retry 3 -O "$url"; done' download \
  "${urls[@]}" >&2 || fail_stage download "the download failed"
available_kb=$(mem_available_kb)
if [ "${available_kb:-0}" -lt "$MERGE_MIN_KB" ]; then
  fail_stage merge "MemAvailable $((${available_kb:-0} / 1024 / 1024)) GB, need 7 GB before the merge"
fi
# shellcheck disable=SC2016 # the script is expanded by the container's sh
planner_compose --profile valhalla-build run --rm -T valhalla-fetch sh -c 'set -e
  apt-get update -qq && apt-get install -y -qq --no-install-recommends osmium-tool
  cd /work && osmium merge src/*.osm.pbf -o alps.osm.pbf --overwrite' merge >&2 ||
  fail_stage merge "the merge failed"
# The scripted image may build from every *.pbf it finds: only the merged file stays.
docker run --rm --network none -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
  sh -c 'rm -rf /vol/build/src' drop-src >&2 || fail_stage merge "cannot delete the extracts"

# 3. Stop serving, build, apply the overrides.
say "tiles-refresh: stopping the routing engine; a plan being calculated now ends with 'Routing engine unreachable - nothing was changed'"
planner_compose stop valhalla >&2 || fail_stage build "valhalla did not stop"
planner_compose --profile valhalla-build run --rm -T valhalla-build >&2 || fail_stage build "the tile build failed"
# shellcheck disable=SC2016 # the script is expanded by the container's sh
planner_compose --profile valhalla-build run --rm -T -v "$PWD/valhalla/valhalla.overrides.json:/overrides.json:ro" \
  --entrypoint sh valhalla-build -c 'set -e
  jq -s ".[0] * .[1]" /custom_files/valhalla.json /overrides.json >/custom_files/valhalla.json.new
  mv /custom_files/valhalla.json.new /custom_files/valhalla.json' overrides >&2 ||
  fail_stage overrides "applying valhalla.overrides.json failed"

# 4. Promote, switch, check.
# shellcheck disable=SC2016 # the script is expanded by the container's sh
docker run --rm --network none -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
  sh -c 'set -e; name=$1; shift; part="/vol/tilesets/.$name.partial"
    rm -rf "$part"; mkdir -p "$part"
    for f in "$@"; do mv "/vol/build/$f" "$part/$f"; done
    (cd "$part" && sha256sum "$@" >SHA256SUMS)
    mv "$part" "/vol/tilesets/$name"; rm -rf /vol/build' promote "$NEW" "${TILES_FILES[@]}" >&2 ||
  fail_stage promote "could not move the built files to tilesets/$NEW"
backup_routing
write_routing "$NEW" || undo_switch "cannot write routing.env"
planner_compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" valhalla >&2 ||
  undo_switch "valhalla did not become healthy within ${WAIT_TIMEOUT} s on tileset $NEW"
valhalla_status || undo_switch "valhalla /status did not answer"
MODIFIED=$VALHALLA_MODIFIED
if [ "$VALHALLA_VERSION" != "$VALHALLA_VERSION_WANTED" ]; then
  undo_switch "valhalla reports version '$VALHALLA_VERSION', expected $VALHALLA_VERSION_WANTED"
fi
discard_routing_backup

# 5. The new tileset passed: only it and the previous one stay.
# shellcheck disable=SC2016 # the script is expanded by the container's sh
docker run --rm --network none -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
  sh -c 'for d in /vol/tilesets/*; do
    name=${d##*/}
    case $name in
      "$1" | "$2") ;;
      [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) echo "tiles-refresh: deleting tileset $name" >&2; rm -rf "$d" ;;
    esac
  done' prune-tilesets "$NEW" "$current" >&2 || say "tiles-refresh: old tilesets could not be deleted (nothing is lost)"
record ok
say "tiles-refresh: ok: valhalla $VALHALLA_VERSION serves tileset $NEW (tileset_last_modified $MODIFIED; rollback tileset $current)"
say "tiles-refresh: next: make contract-live, then one make acceptance-pi (D95)"
