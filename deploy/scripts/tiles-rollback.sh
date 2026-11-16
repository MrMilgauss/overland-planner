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
# on from the first change to routing.env (backup made) until the engine is verified: any exit in between swaps back
GUARD=off
FAIL_WHY=interrupted

record() { append_tiles_log rollback "$TARGET" "$MODIFIED" "$1" "${2:-}"; }

refuse() {
  say "tiles-rollback: $1"
  record failed "$1"
  exit 1
}

undo() {
  say "tiles-rollback: $1; restoring routing.env"
  FAIL_WHY=$1
  exit 1
}

# The exit trap: while GUARD is on, every exit that is not the verified success (a failed check, a dropped ssh session)
# restores the pointers and starts valhalla on the tileset it came from.
on_exit() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [ "$GUARD" = on ]; then
    GUARD=off
    restore_routing || say "tiles-rollback: routing.env could not be restored; check routing.env and routing.env.prev"
    planner_compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" valhalla >&2 ||
      say "tiles-rollback: valhalla did not come back on the tileset it came from either"
    say "tiles-rollback: $FAIL_WHY"
    record failed "$FAIL_WHY"
    [ "$status" -ne 0 ] || status=1
  fi
  exit "$status"
}
trap on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

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
present=0
volume_has_dir "tilesets/$TARGET" || present=$?
case $present in
  0) ;;
  1) refuse "the previous tileset tilesets/$TARGET is no longer in the volume" ;;
  *) refuse "cannot inspect the volume $VALHALLA_VOLUME (docker did not answer); nothing was changed" ;;
esac

backup_routing || refuse "cannot back up routing.env; nothing was changed"
GUARD=on
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
GUARD=off
record ok
say "tiles-rollback: ok: valhalla $VALHALLA_VERSION serves tileset $TARGET (was $current)"
