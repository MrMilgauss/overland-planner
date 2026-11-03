#!/usr/bin/env bash
# Deploy one planner release on the Pi, loopback first (D89, D91, D165, D176). Run by `make deploy` over ssh:
#
#   cd ~/apps/overland-planner && bash scripts/deploy.sh sha256:<manifest-list digest>
#
#  1 lock (.deploy.lock)          4 stop planner, predeploy snapshot   7 loopback smoke (/healthz, /api/health,
#  2 preflight (compose config,   5 rotate release pointers,             app.started app_version)
#    disk, linux/arm64, unchanged)  rewrite PLANNER_* keys             8 publish on PLANNER_BIND + smoke there
#  3 pull by digest, read labels  6 start on 127.0.0.1 only            9 releases.log line
#
# Failure at 4-7 (nobody on the LAN could write yet): restore the snapshot and the previous release pointers, start,
# smoke and publish the previous release. Failure at 8: digest-only rollback (no snapshot restore; writes may have
# happened, D90). Both log `auto-rollback` with the reason and exit 1. Every outcome appends one releases.log line.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
# shellcheck source=deploy/scripts/lib.sh
. scripts/lib.sh
# Only the .env value may publish; an exported PLANNER_BIND from the ssh session must not.
unset PLANNER_BIND

DIGEST=${1:-}
if ! valid_digest "$DIGEST"; then
  say "usage: scripts/deploy.sh sha256:<64 hex digest of the manifest list>"
  exit 2
fi
TARGET="$PLANNER_REPO@$DIGEST"
NEW_SHA=
NEW_TS=
NEW_HEAD=
SNAPSHOT=
SAVED=
trap 'if [ -n "$SAVED" ]; then rm -rf "$SAVED"; fi' EXIT

record() { append_release_log "$1" "$DIGEST" "$NEW_SHA" "$NEW_TS" "$NEW_HEAD" "$2" "${3:-}"; }

refuse() {
  say "deploy: $1"
  record deploy failed "$1"
  exit 1
}

# The pointer files as they were before this deploy (absent ones stay absent).
save_pointers() {
  local name
  SAVED=$(mktemp -d ./.pointers.XXXXXX) || return 1
  for name in release.env release.env.prev release.env.prev2; do
    if [ -f "$name" ]; then cp -p "$name" "$SAVED/$name" || return 1; fi
  done
}

restore_pointers() {
  local name
  for name in release.env release.env.prev release.env.prev2; do
    if [ -f "$SAVED/$name" ]; then cp -p "$SAVED/$name" "$name"; else rm -f "$name"; fi
  done
}

# roll_back REASON RESTORE_DATA: bring the previous release back (loopback start, smoke, publish), log, exit 1.
roll_back() {
  local reason=$1 restore_data=$2 previous
  say "deploy: $reason; rolling back"
  planner_compose stop planner || say "deploy: stopping the new release failed"
  if [ "$restore_data" = yes ] && [ -n "$SNAPSHOT" ]; then
    if ! restore_snapshot "$SNAPSHOT"; then
      record auto-rollback failed "$reason; restoring snapshot $SNAPSHOT failed, planner left stopped"
      exit 1
    fi
    reason="$reason; restored snapshot $SNAPSHOT"
  fi
  restore_pointers
  previous=$(env_value release.env PLANNER_IMAGE)
  if [ -z "$previous" ]; then
    record auto-rollback failed "$reason; no previous release to start"
    exit 1
  fi
  if start_loopback && smoke_loopback && publish; then
    record auto-rollback ok "$reason; back on ${previous#"$PLANNER_REPO"@}"
  else
    record auto-rollback failed "$reason; previous release did not come back: $FAIL_REASON"
  fi
  exit 1
}

# 1. One deploy at a time.
exec 9>>.deploy.lock
if ! flock -n 9; then
  say "deploy: deploy already running"
  record deploy aborted "deploy already running"
  exit 1
fi

# 2. Preflight. The target image stands in for a missing release.env (first deploy).
PLANNER_IMAGE=$TARGET planner_compose config -q >/dev/null || refuse "preflight: docker compose config failed"
free_kb=$(df -Pk . | awk 'NR == 2 { print $4 }')
[ "${free_kb:-0}" -ge 5242880 ] || refuse "preflight: less than 5 GB free on the install disk"
manifest=$(docker manifest inspect "$TARGET") || refuse "preflight: cannot read the manifest list of $DIGEST"
case $(printf '%s' "$manifest" | tr -d ' \n\r') in
  *'"architecture":"arm64"'*) ;;
  *) refuse "preflight: $DIGEST has no linux/arm64 image" ;;
esac
CURRENT=$(env_value release.env PLANNER_IMAGE)
if [ "$CURRENT" = "$TARGET" ]; then
  NEW_SHA=$(env_value release.env PLANNER_GIT_SHA)
  NEW_TS=$(env_value release.env PLANNER_COMMIT_TS)
  NEW_HEAD=$(env_value release.env PLANNER_ALEMBIC_HEAD)
  record deploy unchanged
  say "deploy: $DIGEST is already deployed (unchanged)"
  exit 0
fi

# 3. Pull by digest; the release facts come from the image labels.
docker pull "$TARGET" >&2 || refuse "pull of $TARGET failed"
labels=$(docker image inspect --format \
  '{{index .Config.Labels "org.opencontainers.image.revision"}} {{index .Config.Labels "org.overland.commit-ts"}} {{index .Config.Labels "org.overland.alembic-head"}}' \
  "$TARGET") || refuse "cannot read the labels of $TARGET"
read -r NEW_SHA NEW_TS NEW_HEAD <<EOF
$labels
EOF
[ -n "$NEW_SHA" ] && [ -n "$NEW_HEAD" ] || refuse "$TARGET lacks the revision or alembic-head label"

# 4. Stop and snapshot (only when a release is installed; the first deploy has nothing to protect).
save_pointers || refuse "cannot save the release pointers"
if [ -n "$CURRENT" ]; then
  planner_compose stop planner || roll_back "stop of the current planner failed" no
  if docker volume inspect "$DATA_VOLUME" >/dev/null 2>&1; then
    name="predeploy-$(date -u +%Y%m%dT%H%M%SZ).tgz"
    snapshot_volume "$name" || roll_back "predeploy snapshot failed" no
    SNAPSHOT=$name
  fi
fi

# 5. Pointers.
rotate_pointers
write_release release.env "$TARGET" "$NEW_SHA" "$NEW_TS" "$NEW_HEAD" || roll_back "writing release.env failed" yes

# 6-7. Loopback start and smoke.
start_loopback || roll_back "$FAIL_REASON" yes
smoke_loopback || roll_back "$FAIL_REASON" yes

# 8. Publish (write gate). From here on a failure keeps the data: digest-only rollback.
publish || roll_back "$FAIL_REASON" no

# 9. Done.
prune_snapshots
record deploy ok
say "deploy: $TARGET serving on $(env_value .env PLANNER_BIND):$(planner_port) (git $NEW_SHA)"
