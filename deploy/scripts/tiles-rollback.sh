#!/usr/bin/env bash
# Switch valhalla back to the previous tileset (D239; ADR-013 Amendment 3). Run by `make tiles-rollback`:
#
#   cd ~/apps/overland-planner && bash scripts/tiles-rollback.sh
#
#  1 routing.env.prev names a tileset whose directory still exists in the volume, else refuse and change nothing
#  2 routing.env and routing.env.prev swap, valhalla is started and waited for, /status is read (version 3.9.1)
#  3 a failed check swaps the pointers back and starts valhalla on the tileset it came from, exit 1
# One tiles.log line per run. The planner is never touched.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
# shellcheck source=deploy/scripts/lib.sh disable=SC1091 # followed by make lint-ci; the pre-commit hook gets no -x
. scripts/lib.sh

TARGET=
MODIFIED=

record() { append_tiles_log rollback "$TARGET" "$MODIFIED" "$1" "${2:-}"; }

refuse() {
  say "tiles-rollback: $1"
  record failed "$1"
  exit 1
}

undo() {
  say "tiles-rollback: $1; restoring routing.env"
  restore_routing
  planner_compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" valhalla >&2 ||
    say "tiles-rollback: valhalla did not come back on the tileset it came from either"
  refuse "$1"
}

exec 9>>.deploy.lock
flock -n 9 || refuse "a deploy, rollback or tiles run is already running"

current=$(env_value routing.env VALHALLA_TILESET)
TARGET=$(env_value routing.env.prev VALHALLA_TILESET)
[ -n "$current" ] || refuse "no routing.env: nothing is served yet"
[ -n "$TARGET" ] || refuse "no previous tileset (routing.env.prev is missing or empty)"
case $TARGET in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) refuse "routing.env.prev names '$TARGET', not an 8-digit tileset" ;;
esac
# shellcheck disable=SC2016 # $1 is expanded by the container's sh
docker run --rm --network none -v "$VALHALLA_VOLUME:/vol:ro" "$SNAPSHOT_IMAGE" \
  sh -c 'test -d "/vol/$1"' tileset-exists "tilesets/$TARGET" >/dev/null 2>&1 ||
  refuse "the previous tileset tilesets/$TARGET is no longer in the volume"

backup_routing
# write_routing keeps the file it replaces as routing.env.prev: the two pointers swap.
write_routing "$TARGET" || undo "cannot write routing.env"
planner_compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" valhalla >&2 ||
  undo "valhalla did not become healthy within ${WAIT_TIMEOUT} s on tileset $TARGET"
valhalla_status || undo "valhalla /status did not answer"
MODIFIED=$VALHALLA_MODIFIED
if [ "$VALHALLA_VERSION" != "$VALHALLA_VERSION_WANTED" ]; then
  undo "valhalla reports version '$VALHALLA_VERSION', expected $VALHALLA_VERSION_WANTED"
fi

discard_routing_backup
record ok
say "tiles-rollback: ok: valhalla $VALHALLA_VERSION serves tileset $TARGET (was $current)"
