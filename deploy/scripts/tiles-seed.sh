#!/usr/bin/env bash
# Seed the first Valhalla tileset from the SPIKE-2R files into the volume overland_valhalla-data and start the engine
# on it (D92, D166, D178, D237; ADR-013 Amendment 3). Run by `make tiles-seed`:
#
#   cd ~/apps/overland-planner && bash scripts/tiles-seed.sh TILESET [SEED_DIR [EXPECT_TILESET_MODIFIED]]
#
#  TILESET  8 digits (YYYYMMDD); SEED_DIR under $HOME (default valhalla-spike/custom_files)
#  1 preflight: the five files exist (default_speeds.json too: the engine has no network to download it), >= 10 GB free, TILESET valid, no other deploy or tiles run (.deploy.lock)
#  2 tilesets/<TILESET>/ absent: copy (plain cp, helper container, --network none) into a .partial directory, verify
#    the copy against the source, write SHA256SUMS, rename. Present with the same checksums: nothing is copied
#    (`unchanged`); present with other content: refused, never overwritten. Present and incomplete (files missing, the
#    ones there equal to the source) and neither served nor kept for rollback: only the missing files are copied
#    (.partial names, verified against the source), SHA256SUMS is rewritten for all five
#  3 routing.env <- VALHALLA_TILESET=<TILESET> (the previous one kept as routing.env.prev), valhalla started and
#    waited for, /status read inside the compose network: version 3.9.1 and, when given, tileset_last_modified equal
#    to EXPECT_TILESET_MODIFIED. Otherwise routing.env (and .prev) come back as they were, valhalla is stopped when it
#    was not running before, exit 1. The planner is never touched. One tiles.log line per run.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
# shellcheck source=deploy/scripts/lib.sh
. scripts/lib.sh

TILESET=${1:-}
SEED_DIR=${2:-valhalla-spike/custom_files}
EXPECT=${3:-}
MIN_FREE_KB=$((10 * 1024 * 1024))
MODIFIED=
WAS_RUNNING=
COPIED=no
POINTER_CHANGED=no
# on from the first change to routing.env (backup made) until the engine is verified: any exit in between puts it back
GUARD=off
FAIL_WHY=interrupted

record() { append_tiles_log seed "$TILESET" "$MODIFIED" "$1" "${2:-}"; }

refuse() {
  say "tiles-seed: $1"
  record failed "$1"
  exit "${2:-1}"
}

drop_partial() {
  # shellcheck disable=SC2016 # $1 is expanded by the container's sh
  docker run --rm --network none -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
    sh -c 'rm -rf "/vol/tilesets/.$1.partial"' drop-partial "$TILESET" >&2 || true
}

# undo REASON: the engine did not come up on the new tileset; the exit trap puts the pointers back.
undo() {
  say "tiles-seed: $1; restoring routing.env"
  FAIL_WHY=$1
  exit 1
}

# The exit trap: while GUARD is on, every exit that is not the verified success (a failed start, a dropped ssh session)
# restores routing.env and .prev and returns valhalla to how it was: stopped when it was not running before, started
# again when it was.
on_exit() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [ "$GUARD" = on ]; then
    GUARD=off
    if [ -z "$WAS_RUNNING" ]; then planner_compose stop valhalla >&2 || true; fi
    restore_routing || say "tiles-seed: routing.env could not be restored; check routing.env and routing.env.prev"
    if [ -n "$WAS_RUNNING" ]; then
      planner_compose up -d valhalla >&2 || say "tiles-seed: the previous valhalla did not come back either"
    fi
    say "tiles-seed: $FAIL_WHY"
    record failed "$FAIL_WHY"
    [ "$status" -ne 0 ] || status=1
  fi
  exit "$status"
}
trap on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# complete_tileset: copy the files in $missing into the existing tilesets/$TILESET under .partial names, verify them against
# the source, give them their final names and rewrite SHA256SUMS for all five. Files already there are never written.
complete_tileset() {
  local expected want
  say "tiles-seed: tilesets/$TILESET misses ${missing[*]}; copying only those"
  # shellcheck disable=SC2016 # the script is expanded by the container's sh
  docker run --rm --network none -v "$SOURCE:/seed:ro" -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
    sh -c 'set -e; dir="/vol/tilesets/$1"; shift
      for f in "$@"; do echo "tiles-seed: copying $f" >&2; cp "/seed/$f" "$dir/$f.partial"; done' complete-tileset "$TILESET" "${missing[@]}" >&2 ||
    {
      drop_missing_partials
      refuse "copy into tilesets/$TILESET failed"
    }
  expected=
  for want in "${missing[@]}"; do expected="$expected$(printf '%s\n' "$SOURCE_SUMS" | grep -F "  $want")
"; done
  # shellcheck disable=SC2016 # "$@" is expanded by the container's sh
  copy_sums=$(docker run --rm --network none -v "$VALHALLA_VOLUME:/vol:ro" "$SNAPSHOT_IMAGE" \
    sh -c 'cd "/vol/tilesets/$1" && shift && for f in "$@"; do sha256sum "$f.partial" | sed "s/[.]partial\$//"; done' verify-missing "$TILESET" "${missing[@]}") ||
    copy_sums=
  if [ "$copy_sums" != "$(printf '%s' "$expected")" ]; then
    drop_missing_partials
    refuse "checksum of the copy differs from the source: $(sums_diff "$expected" "$copy_sums"); nothing kept"
  fi
  # shellcheck disable=SC2016 # the script is expanded by the container's sh
  docker run --rm --network none -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
    sh -c 'set -e; dir="/vol/tilesets/$1"; sums=$2; shift 2
      for f in "$@"; do [ ! -e "$dir/$f" ] || exit 1; done
      for f in "$@"; do mv "$dir/$f.partial" "$dir/$f"; done
      printf "%s\n" "$sums" >"$dir/SHA256SUMS.partial"; mv "$dir/SHA256SUMS.partial" "$dir/SHA256SUMS"' finalize-missing "$TILESET" "$SOURCE_SUMS" "${missing[@]}" >&2 ||
    {
      drop_missing_partials
      refuse "could not finish tilesets/$TILESET"
    }
}

drop_missing_partials() {
  # shellcheck disable=SC2016 # the script is expanded by the container's sh
  docker run --rm --network none -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
    sh -c 'cd "/vol/tilesets/$1" && rm -f ./*.partial' drop-partial "$TILESET" >&2 || true
}

# 1. Preflight.
case $TILESET in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) refuse "TILESET must be 8 digits (YYYYMMDD), got '$TILESET'" 2 ;;
esac
case $SEED_DIR in
  '' | /* | *..* | *[!A-Za-z0-9._/-]*) refuse "SEED_DIR must be a plain path under the home directory, got '$SEED_DIR'" 2 ;;
esac
case $EXPECT in
  *[!0-9]*) refuse "EXPECT_TILESET_MODIFIED must be digits, got '$EXPECT'" 2 ;;
esac
SOURCE="$HOME/${SEED_DIR%/}"
for file in "${TILES_FILES[@]}"; do
  [ -f "$SOURCE/$file" ] || refuse "missing file $file in ~/${SEED_DIR%/}"
done
root=${DOCKER_ROOT:-/var/lib/docker}
[ -d "$root" ] || root=$HOME
free_kb=$(df -Pk "$root" 2>/dev/null | awk 'NR == 2 { print $4 }')
if [ "${free_kb:-0}" -lt "$MIN_FREE_KB" ]; then
  refuse "disk: only $((${free_kb:-0} / 1024)) MB free (need 10 GB)"
fi
exec 9>>.deploy.lock
flock -n 9 || refuse "a deploy, rollback or tiles run is already running"

say "tiles-seed: checksums of the source files (this takes a while)"
SOURCE_SUMS=$(dir_sums source-sums "$SOURCE") || refuse "cannot read the source files in ~/${SEED_DIR%/}"
WAS_RUNNING=$(docker ps -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
  --filter label=com.docker.compose.service=valhalla) ||
  refuse "cannot tell whether valhalla is running (docker ps failed); nothing was changed"

# 2. The tileset directory.
present=0
volume_has_dir "tilesets/$TILESET" || present=$?
case $present in 0 | 1) ;; *) refuse "cannot inspect the volume $VALHALLA_VOLUME (docker did not answer); nothing was changed" ;; esac
if [ "$present" -eq 0 ]; then
  present_sums=$(volume_present_sums tileset-sums "tilesets/$TILESET") || present_sums=
  missing=()
  foreign=
  for file in "${TILES_FILES[@]}"; do
    line=$(printf '%s\n' "$present_sums" | grep -F "  $file" || true)
    if [ -z "$line" ]; then
      missing+=("$file")
    elif ! printf '%s\n' "$SOURCE_SUMS" | grep -qxF "$line"; then
      foreign="$foreign$file "
    fi
  done
  if [ -n "$foreign" ]; then
    refuse "tilesets/$TILESET already holds different content (differs: ${foreign}); not overwritten"
  fi
  if [ "${#missing[@]}" -eq 0 ]; then
    stored_sums=$(volume_stored_sums "tilesets/$TILESET") || stored_sums=
    if [ "$stored_sums" != "$SOURCE_SUMS" ]; then
      refuse "tilesets/$TILESET already holds different content (differs: SHA256SUMS: $(sums_diff "$SOURCE_SUMS" "$stored_sums")); not overwritten"
    fi
    say "tiles-seed: tilesets/$TILESET already holds these files; nothing to copy"
  else
    if [ "$(env_value routing.env VALHALLA_TILESET)" = "$TILESET" ] || [ "$(env_value routing.env.prev VALHALLA_TILESET)" = "$TILESET" ]; then
      refuse "tilesets/$TILESET is incomplete (missing: ${missing[*]}) but served or kept for rollback; not written into"
    fi
    complete_tileset
    COPIED=yes
  fi
else
  say "tiles-seed: copying about 5 GB into tilesets/$TILESET (progress below)"
  # shellcheck disable=SC2016 # the script is expanded by the container's sh
  docker run --rm --network none -v "$SOURCE:/seed:ro" -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
    sh -c 'set -e; part="/vol/tilesets/.$1.partial"; shift; rm -rf "$part"; mkdir -p "$part"
      for f in "$@"; do echo "tiles-seed: copying $f" >&2; cp "/seed/$f" "$part/$f"; done' copy-tileset "$TILESET" "${TILES_FILES[@]}" >&2 ||
    {
      drop_partial
      refuse "copy into tilesets/$TILESET failed"
    }
  say "tiles-seed: verifying the copy against the source"
  copy_sums=$(volume_sums verify-copy "tilesets/.$TILESET.partial") || copy_sums=
  if [ "$copy_sums" != "$SOURCE_SUMS" ]; then
    drop_partial
    refuse "checksum of the copy differs from the source: $(sums_diff "$SOURCE_SUMS" "$copy_sums"); nothing kept"
  fi
  # shellcheck disable=SC2016 # the script is expanded by the container's sh
  docker run --rm --network none -v "$VALHALLA_VOLUME:/vol" "$SNAPSHOT_IMAGE" \
    sh -c 'set -e; [ ! -e "/vol/tilesets/$1" ] || exit 1
      printf "%s\n" "$2" >"/vol/tilesets/.$1.partial/SHA256SUMS"
      mv "/vol/tilesets/.$1.partial" "/vol/tilesets/$1"' finalize-tileset "$TILESET" "$SOURCE_SUMS" >&2 ||
    {
      drop_partial
      refuse "could not finish tilesets/$TILESET"
    }
  COPIED=yes
fi

# 3. Pointer, start, status.
current=$(env_value routing.env VALHALLA_TILESET)
backup_routing || refuse "cannot back up routing.env; nothing was changed"
GUARD=on
if [ "$current" != "$TILESET" ]; then
  write_routing "$TILESET" || undo "cannot write routing.env"
  POINTER_CHANGED=yes
fi
planner_compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" valhalla >&2 ||
  undo "valhalla did not become healthy within ${WAIT_TIMEOUT} s on tileset $TILESET"
valhalla_status || undo "valhalla /status did not answer"
MODIFIED=$VALHALLA_MODIFIED
if [ "$VALHALLA_VERSION" != "$VALHALLA_VERSION_WANTED" ]; then
  undo "valhalla reports version '$VALHALLA_VERSION', expected $VALHALLA_VERSION_WANTED"
fi
if [ -n "$EXPECT" ] && [ "$VALHALLA_MODIFIED" != "$EXPECT" ]; then
  undo "tileset_last_modified is '$VALHALLA_MODIFIED', expected $EXPECT"
fi

discard_routing_backup
GUARD=off
if [ "$COPIED" = no ] && [ "$POINTER_CHANGED" = no ]; then result=unchanged; else result=ok; fi
record "$result"
say "tiles-seed: $result: valhalla $VALHALLA_VERSION serves tileset $TILESET (tileset_last_modified $MODIFIED)"
