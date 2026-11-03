#!/usr/bin/env bash
# Roll the planner back one or two releases on the Pi (D90, D91, D165, D166, D176, D195). Run by `make rollback`:
#
#   cd ~/apps/overland-planner && bash scripts/rollback.sh [1|2]
#
#  1 target: release.env.prev (1) or release.env.prev2 (2); already serving it -> `unchanged`, exit 0
#  2 lock (.deploy.lock, shared with deploy.sh)
#  3 the target image must still be on the Pi (no pull: only a digest verified when it was deployed comes back, D195)
#  4 differing org.overland.alembic-head labels: stop the planner, fresh prerollback snapshot, warn that newer-schema
#    data can be lost, `alembic downgrade <target head>` with the CURRENT image. A failed downgrade restores the
#    predeploy snapshot of the deploy being rolled back (its timestamp printed first); without one, the fresh
#    snapshot comes back and the current release keeps serving (exit 1)
#  5 release.env -> release.env.failed; rewrite only the PLANNER_* keys of release.env. release.env.prev/.prev2 stay
#    as they are, so a repeated rollback never flips back to the failed release
#  6 the same loopback start, smoke and publish as deploy.sh (D165)
#  7 one releases.log line (action `rollback`). routing.env is never written (D166).
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
# shellcheck source=deploy/scripts/lib.sh
. scripts/lib.sh
unset PLANNER_BIND

STEPS=${1:-1}
TARGET=
NEW_SHA=
NEW_TS=
NEW_HEAD=
DATA_NOTE=

record() { append_release_log rollback "${TARGET#"$PLANNER_REPO"@}" "$NEW_SHA" "$NEW_TS" "$NEW_HEAD" "$1" "${2:-}"; }

refuse() {
  say "rollback: $1"
  record failed "$1"
  exit 1
}

# keep_current REASON: the current release (release.env untouched) serves again; log `failed`, exit 1.
keep_current() {
  say "rollback: $1; bringing the current release back"
  if start_loopback && smoke_loopback && publish; then
    record failed "$1; still serving ${CURRENT#"$PLANNER_REPO"@}"
  else
    record failed "$1; current release did not come back: $FAIL_REASON"
  fi
  exit 1
}

alembic_head_of() {
  docker image inspect --format '{{index .Config.Labels "org.overland.alembic-head"}}' "$1"
}

# predeploy_snapshot_of IMAGE: the newest snapshots/predeploy-<ts>.tgz taken no later than the last successful
# deploy of IMAGE (deploy.sh snapshots before it logs), or nothing.
predeploy_snapshot_of() {
  local digest=${1#"$PLANNER_REPO"@} deployed file stamp best=
  deployed=$(grep -F '"action":"deploy"' releases.log 2>/dev/null | grep -F "\"digest\":\"$digest\"" |
    grep -F '"result":"ok"' | tail -n 1 | sed -nE 's/^\{"ts":"([^"]*)".*/\1/p' | tr -d ':-')
  if [ -z "$deployed" ]; then return 0; fi
  for file in snapshots/predeploy-*.tgz; do
    stamp=${file#snapshots/predeploy-}
    stamp=${stamp%.tgz}
    if [ -f "$file" ] && ! [ "$stamp" \> "$deployed" ]; then best=${file#snapshots/}; fi
  done
  printf '%s\n' "$best"
}

snapshot_time() {
  printf '%s\n' "$1" | sed -E 's/^predeploy-([0-9]{4})([0-9]{2})([0-9]{2})T([0-9]{2})([0-9]{2})([0-9]{2})Z\.tgz$/\1-\2-\3 \4:\5:\6 UTC/'
}

# Schema step (D90): runs with the planner stopped and the current image still in release.env.
downgrade_schema() {
  local current_head=$1 fresh snapshot taken
  planner_compose stop planner || refuse "stop of the current planner failed"
  fresh="prerollback-$(date -u +%Y%m%dT%H%M%SZ).tgz"
  snapshot_volume "$fresh" || keep_current "prerollback snapshot failed"
  say "rollback: schema $current_head -> $NEW_HEAD: downgrading with the current image;" \
    "data that only the newer schema holds can be lost (D91)"
  if planner_compose run --rm planner alembic downgrade "$NEW_HEAD" >&2; then
    return 0
  fi
  snapshot=$(predeploy_snapshot_of "$(env_value "$ROLLED_BACK" PLANNER_IMAGE)")
  if [ -z "$snapshot" ]; then
    restore_snapshot "$fresh" || refuse "schema downgrade failed; restoring $fresh failed, planner left stopped"
    keep_current "schema downgrade to $NEW_HEAD failed and no predeploy snapshot found; restored $fresh"
  fi
  taken=$(snapshot_time "$snapshot")
  say "rollback: schema downgrade failed; restoring $snapshot taken $taken: data written since then is lost"
  restore_snapshot "$snapshot" || refuse "schema downgrade failed; restoring $snapshot failed, planner left stopped"
  DATA_NOTE="schema downgrade failed (to $NEW_HEAD); restored $snapshot (data written since $taken lost)"
}

# 1. Target.
case $STEPS in
  1) POINTER=release.env.prev ROLLED_BACK=release.env ;;
  2) POINTER=release.env.prev2 ROLLED_BACK=release.env.prev ;;
  *)
    say "usage: scripts/rollback.sh [1|2]"
    record failed "STEPS must be 1 or 2, got '$STEPS'"
    exit 2
    ;;
esac
TARGET=$(env_value "$POINTER" PLANNER_IMAGE)
NEW_SHA=$(env_value "$POINTER" PLANNER_GIT_SHA)
NEW_TS=$(env_value "$POINTER" PLANNER_COMMIT_TS)
NEW_HEAD=$(env_value "$POINTER" PLANNER_ALEMBIC_HEAD)
CURRENT=$(env_value release.env PLANNER_IMAGE)

# 2. One deploy or rollback at a time.
exec 9>>.deploy.lock
if ! flock -n 9; then
  say "rollback: a deploy or rollback is already running"
  record aborted "deploy or rollback already running"
  exit 1
fi

if [ -z "$TARGET" ]; then refuse "$POINTER has no release to roll back to"; fi
if [ "$TARGET" = "$CURRENT" ]; then
  record unchanged
  say "rollback: already serving $TARGET (unchanged)"
  exit 0
fi

# 3. Only an image still on the Pi; its provenance was verified when it was deployed (D195).
target_head=$(alembic_head_of "$TARGET") ||
  refuse "$TARGET is not on the Pi any more; deploy it again with make deploy SHA=$NEW_SHA"
current_head=$(alembic_head_of "$CURRENT") || refuse "cannot read the labels of the current image $CURRENT"
NEW_HEAD=${target_head:-$NEW_HEAD}

# 4. Schema.
if [ "$target_head" != "$current_head" ]; then downgrade_schema "$current_head"; fi

# 5. Pointers.
cp -p release.env release.env.failed || refuse "cannot keep release.env as release.env.failed"
write_release release.env "$TARGET" "$NEW_SHA" "$NEW_TS" "$NEW_HEAD" || refuse "writing release.env failed"

# 6-7. Loopback start, smoke, publish.
if start_loopback && smoke_loopback && publish; then
  record ok "$DATA_NOTE"
  say "rollback: $TARGET serving on $(env_value .env PLANNER_BIND):$(planner_port) (git $NEW_SHA)"
  exit 0
fi
refuse "$FAIL_REASON"
