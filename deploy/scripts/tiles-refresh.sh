#!/usr/bin/env bash
# Quarterly map-data refresh of the Valhalla tileset (D83, D92, D166, D237, D239, D240; ADR-013 Amendment 3). Run by
# `make tiles-refresh`, at a start time the owner names (about 40 minutes without routing):
#
#   cd ~/apps/overland-planner && bash scripts/tiles-refresh.sh
#
#  1 preflight, read-only: routing.env exists (make tiles-seed came first); the new tileset is named by the UTC date and
#    is neither served (routing.env), kept for rollback (routing.env.prev) nor already in the volume; disk free >= 25 GB;
#    MemAvailable >= build cap + 1 GiB; the planner's /api/diagnostics is asked (a note when it does not answer)
#  2 while valhalla serves: valhalla-fetch (the only service with egress) downloads the eight Geofabrik extracts into
#    build/src and default_speeds.json into build/ (the build has no network and would fail without it), and merges the
#    extracts into build/alps.osm.pbf (MemAvailable >= 7 GiB checked again just before the merge); the extracts are deleted.
#    The time-zone db is carried over from the serving tileset into build/ (the build has no network and cannot download it)
#  3 valhalla stopped, valhalla-build makes the tiles under its cap, the deltas of valhalla/valhalla.overrides.json are
#    applied to the built valhalla.json with jq inside the Valhalla image
#  4 promote the five tileset files to tilesets/<YYYYMMDD>/ (with SHA256SUMS), build/ deleted; routing.env -> routing.env.prev, new pointer,
#    valhalla started and waited for, /status read (version 3.9.1)
#  5 only then: every tileset but the new and the previous one is deleted; tiles.log gets `ok`
# Any failure before 4 starts valhalla again on the old tileset (routing.env untouched); a failed switch restores
# routing.env and .prev, starts the old tileset and keeps the new directory for inspection. One tiles.log line per run.
# An interrupted run (the ssh session drops) is a failed run: valhalla starts on the old tileset, the pointers come back.
# After the switch /status must name other map data (tileset_last_modified) than before the stop.
# With REGIONS_FILE (the helper's list, D303/D313: one region per line, six tab-separated fields: key, name, parent name,
# .osm.pbf address, .poly address, bytes) the extracts are the file's, saved as src/<n>.osm.pbf by position, each .poly
# is fetched into /meta/outlines/ (road-map-meta of the volume) first, and the disk needed is max(25 GB, 3.9 x bytes);
# a held lock exits 75 and logs nothing. Without it the eight EXTRACTS below are the default.
# The planner is never touched. Seams for the offline tests: TILES_DATE (the UTC date), MEMINFO (/proc/meminfo),
# DOCKER_ROOT (the disk checked).
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
# shellcheck source=deploy/scripts/lib.sh disable=SC1091 # followed by make lint-ci; the pre-commit hook gets no -x
. scripts/lib.sh

NEW=${TILES_DATE:-$(date -u +%Y%m%d)}
GEOFABRIK=https://download.geofabrik.de
SPEEDS_URL=https://raw.githubusercontent.com/OpenStreetMapSpeeds/schema/master/default_speeds.json
EXTRACTS=(europe/italy-latest europe/spain-latest europe/switzerland-latest europe/austria-latest europe/france/rhone-alpes-latest
  europe/france/provence-alpes-cote-d-azur-latest europe/france/languedoc-roussillon-latest europe/france/midi-pyrenees-latest)
MIN_FREE_KB=$((25 * 1024 * 1024))
REGIONS=()    # key, pbf address, poly address per region (REGIONS_FILE only)
DOWNLOAD_BYTES=0
NEED_GB=25
MERGE_MIN_KB=$((7 * 1024 * 1024))
MODIFIED=
OLD_MODIFIED=
# on from the start of the download until the switch has passed: any exit in between starts valhalla on the old tileset
# again (the engine may be stopped) and puts the pointers back when they were backed up.
GUARD=off
POINTERS_BACKED_UP=no
FAIL_WHY="refresh failed (interrupted)"
FAILED_LOGGED=no

record() {
  append_tiles_log refresh "$NEW" "$MODIFIED" "$1" "${2:-}"
  if [ "$1" = failed ]; then FAILED_LOGGED=yes; fi
}

# refuse WHY: a preflight refusal, nothing was changed.
refuse() {
  say "tiles-refresh: $1"
  record failed "$1"
  exit 1
}

# fail_stage STAGE WHY: the old tileset keeps (or gets back) the serving; the exit trap starts it and logs the line.
fail_stage() {
  say "tiles-refresh: $2; starting valhalla on the old tileset again"
  FAIL_WHY="refresh failed ($1)"
  exit 1
}

# undo_switch WHY: pointers back as they were, valhalla on the old tileset, the new directory stays for inspection.
undo_switch() {
  say "tiles-refresh: $1; restoring routing.env, tilesets/$NEW is kept for inspection"
  FAIL_WHY="refresh failed (switch)"
  exit 1
}

on_exit() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [ "$GUARD" = on ]; then
    GUARD=off
    if [ "$POINTERS_BACKED_UP" = yes ]; then
      restore_routing || say "tiles-refresh: routing.env could not be restored; check routing.env and routing.env.prev"
    fi
    planner_compose up -d valhalla >&2 || say "tiles-refresh: the old valhalla did not start either"
    if [ "$FAILED_LOGGED" = no ]; then record failed "$FAIL_WHY"; fi
    [ "$status" -ne 0 ] || status=1
  fi
  exit "$status"
}
trap on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

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

# usable_address ADDRESS: https and only the characters of a plain address (it travels as an argument, never evaluated).
usable_address() {
  case $1 in
    https://?*) ;;
    *) return 1 ;;
  esac
  case $1 in *[!A-Za-z0-9._/:-]*) return 1 ;; esac
}

# read_regions: REGIONS_FILE line by line (never sourced or evaluated) into REGIONS and DOWNLOAD_BYTES.
read_regions() {
  local line key pbf poly bytes
  [ -f "$REGIONS_FILE" ] || refuse "REGIONS_FILE $REGIONS_FILE is not a file"
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] || continue
    key=$(printf '%s' "$line" | cut -f1)
    pbf=$(printf '%s' "$line" | cut -f4)
    poly=$(printf '%s' "$line" | cut -f5)
    bytes=$(printf '%s' "$line" | cut -f6)
    case $key in '' | *[!a-z0-9/-]* | /* | */ | *..*) refuse "the regions file names a region key '$key' that is not a key" ;; esac
    usable_address "$pbf" || refuse "region $key: the .osm.pbf address is not usable"
    usable_address "$poly" || refuse "region $key: the .poly address is not usable"
    case $bytes in '' | *[!0-9]*) refuse "region $key: the download size is not a number of bytes" ;; esac
    REGIONS+=("$key" "$pbf" "$poly")
    DOWNLOAD_BYTES=$((DOWNLOAD_BYTES + bytes))
  done <"$REGIONS_FILE"
  [ "${#REGIONS[@]}" -gt 0 ] || refuse "the regions file lists no region"
}

# 1. Preflight.
exec 9>>.deploy.lock
if ! flock -n 9; then
  say "tiles-refresh: a deploy, rollback or tiles run is already running; nothing was done"
  exit 75
fi
if [ -n "${REGIONS_FILE:-}" ]; then
  read_regions
  # 3.9 x the download (decimal GB, as the list counts them), never below 25 GB
  if [ $((DOWNLOAD_BYTES * 39 / 10)) -gt $((25 * 1024 * 1024 * 1024)) ]; then
    MIN_FREE_KB=$((DOWNLOAD_BYTES * 39 / 10 / 1024))
    NEED_GB=$((DOWNLOAD_BYTES * 39 / 10 / 1000000000))
  fi
fi
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
present=0
volume_has_dir "tilesets/$NEW" || present=$?
case $present in
  0) refuse "tilesets/$NEW already exists; one refresh a day at most, nothing is overwritten" ;;
  1) ;;
  *) refuse "cannot inspect the volume $VALHALLA_VOLUME (docker did not answer); nothing was changed" ;;
esac
root=${DOCKER_ROOT:-/var/lib/docker}
[ -d "$root" ] || root=$HOME
free_kb=$(df -Pk "$root" 2>/dev/null | awk 'NR == 2 { print $4 }')
if [ "${free_kb:-0}" -lt "$MIN_FREE_KB" ]; then
  refuse "disk: only $((${free_kb:-0} / 1024 / 1024)) GB free (need $NEED_GB GB)"
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
# The map data served now: after the switch /status must name other map data, or the new tileset is not what answers.
valhalla_status || refuse "valhalla /status did not answer (or names no tileset_last_modified); nothing was changed"
OLD_MODIFIED=$VALHALLA_MODIFIED

# 2. Download and merge while valhalla serves.
GUARD=on
say "tiles-refresh: tileset $NEW; downloading and merging while the old tileset serves"
PREPARE_SH='rm -rf /vol/build && mkdir -p /vol/build/src'
[ -z "${REGIONS_FILE:-}" ] || PREPARE_SH='rm -rf /vol/build /vol/road-map-meta && mkdir -p /vol/build/src /vol/road-map-meta/outlines'
# shellcheck disable=SC2016 # the script is expanded by the container's sh
docker run --rm --network none -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
  sh -c "$PREPARE_SH" prepare-build >&2 ||
  fail_stage download "cannot prepare build/ in the volume"
# The build has no network (D239) and valhalla_build_timezones downloads: the serving tileset's db is reused.
# shellcheck disable=SC2016 # the script is expanded by the container's sh
docker run --rm --network none -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
  sh -c 'test -s "/vol/tilesets/$1/timezones.sqlite" && cp "/vol/tilesets/$1/timezones.sqlite" /vol/build/timezones.sqlite' \
  carry-timezones "$current" >&2 ||
  fail_stage download "tilesets/$current/timezones.sqlite is missing or empty; the build has no network to download it"
# The download is a list of DESTINATION ADDRESS pairs: the borders first (a 404 stops the refresh before anything is
# stopped), then default_speeds.json, then the extracts. A refused pair names its destination on stderr.
pairs=()
if [ -n "${REGIONS_FILE:-}" ]; then
  for ((i = 0; i < ${#REGIONS[@]}; i += 3)); do
    pairs+=("/meta/outlines/${REGIONS[i]//\//-}.poly" "${REGIONS[i + 2]}")
  done
fi
pairs+=(/work/default_speeds.json "$SPEEDS_URL")
if [ -n "${REGIONS_FILE:-}" ]; then
  for ((i = 0; i < ${#REGIONS[@]}; i += 3)); do pairs+=("/work/src/$((i / 3 + 1)).osm.pbf" "${REGIONS[i + 1]}"); done
else
  for extract in "${EXTRACTS[@]}"; do pairs+=("/work/src/${extract##*/}.osm.pbf" "$GEOFABRIK/$extract.osm.pbf"); done
fi
fetch_err=$(mktemp) || fail_stage download "cannot make a temporary file"
# shellcheck disable=SC2016 # the script is expanded by the container's sh
planner_compose --profile valhalla-build run --rm -T valhalla-fetch sh -c 'set -e
  apt-get update -qq && apt-get install -y -qq --no-install-recommends curl ca-certificates
  while [ $# -gt 0 ]; do
    echo "tiles-refresh: downloading $2" >&2
    curl -fL --retry 3 -o "$1" "$2" || { echo "tiles-refresh: not fetched: $1" >&2; exit 22; }
    shift 2
  done' download "${pairs[@]}" >&2 2>"$fetch_err"
fetch_status=$?
cat "$fetch_err" >&2
if [ "$fetch_status" -ne 0 ]; then
  border=$(sed -n 's|.*not fetched: /meta/outlines/\(.*\)\.poly$|\1|p' "$fetch_err" | head -n 1)
  if [ -z "$border" ] && [ -n "${REGIONS_FILE:-}" ] && grep -q 404 "$fetch_err"; then
    for ((i = 0; i < ${#REGIONS[@]}; i += 3)); do border="${border:+$border, }${REGIONS[i]}"; done
    border="(one of: $border)"
  fi
  rm -f "$fetch_err"
  if [ -n "$border" ]; then fail_stage download "the border file of region $border was not found (region_missing)"; fi
  fail_stage download "the download failed"
fi
rm -f "$fetch_err"
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
    [ ! -e "/vol/tilesets/$name" ] || exit 1
    rm -rf "$part"; mkdir -p "$part"
    for f in "$@"; do mv "/vol/build/$f" "$part/$f"; done
    (cd "$part" && sha256sum "$@" >SHA256SUMS)
    mv "$part" "/vol/tilesets/$name"; rm -rf /vol/build' promote "$NEW" "${TILES_FILES[@]}" >&2 ||
  fail_stage promote "could not move the built files to tilesets/$NEW"
backup_routing || fail_stage switch "cannot back up routing.env"
POINTERS_BACKED_UP=yes
write_routing "$NEW" || undo_switch "cannot write routing.env"
planner_compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" valhalla >&2 ||
  undo_switch "valhalla did not become healthy within ${WAIT_TIMEOUT} s on tileset $NEW"
valhalla_status || undo_switch "valhalla /status did not answer"
MODIFIED=$VALHALLA_MODIFIED
if [ "$VALHALLA_VERSION" != "$VALHALLA_VERSION_WANTED" ]; then
  undo_switch "valhalla reports version '$VALHALLA_VERSION', expected $VALHALLA_VERSION_WANTED"
fi
if [ "$VALHALLA_MODIFIED" = "$OLD_MODIFIED" ]; then
  undo_switch "valhalla still serves the old map data (tileset_last_modified $OLD_MODIFIED)"
fi
discard_routing_backup
GUARD=off

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
