#!/usr/bin/env bash
# The road-map helper as one timed job of the deploy user (D303, D314; ADR-013 Amendment 5):
#
#   cd ~/apps/overland-planner && bash scripts/road-map-helper.sh install | uninstall | status
#
# install   one crontab line, run every minute from this install folder, marked so that it is found again; an older line
#           of the helper is replaced, every other line is kept byte for byte, in order
# uninstall removes only the marked line; with no crontab (or no marked line) it writes nothing and succeeds
# status    "installed" (exit 0) or "not installed" (exit 1); never changes anything
# The crontab is edited safely: only "no crontab for <user>" counts as an empty list (any other failure to read it leaves
# the Pi alone, exit 1); the old list is saved in this folder; the new one goes in as a file (never a pipe), is read back and
# compared, and the saved list is put back on a difference (exit 1, a warning). Never sudo.
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1
# shellcheck source=deploy/scripts/lib.sh disable=SC1091 # followed by make lint-ci; the pre-commit hook gets no -x
. scripts/lib.sh

MARKER='# overland-road-map-runner'
CURRENT=.road-map-crontab.cur.$$
NEW=.road-map-crontab.new.$$
CHECK=.road-map-crontab.chk.$$
trap 'rm -f "$CURRENT" "$NEW" "$NEW.tmp" "$CHECK"' EXIT

# read_jobs: the user's crontab in $CURRENT (empty when there is none); non-zero, with one line, when it cannot be read.
READ_ERROR=
read_jobs() {
  local status=0
  READ_ERROR=$(crontab -l 2>&1 >"$CURRENT") || status=$?
  [ "$status" -eq 0 ] && return 0
  case $READ_ERROR in
    *"no crontab for "*) : >"$CURRENT"; HAD_JOBS=no; return 0 ;;
  esac
  return 1
}
HAD_JOBS=yes

# without_helper IN OUT: every line but the helper's own (the marker ends it).
without_helper() {
  awk -v marker="$MARKER" '{ n = length(marker); if (length($0) >= n && substr($0, length($0) - n + 1) == marker) next; print }' "$1" >"$2"
}

# helper_line: run every minute from this folder; the folder is quoted for sh, a % is escaped for cron.
helper_line() {
  local quoted=${PWD//\'/\'\\\'\'}
  quoted=${quoted//%/\\%}
  printf '* * * * * cd '"'"'%s'"'"' && bash scripts/road-map-runner.sh >>road-map-runner.log 2>&1 %s\n' "$quoted" "$MARKER"
}

has_helper() {
  without_helper "$CURRENT" "$CHECK"
  ! cmp -s "$CURRENT" "$CHECK"
}

# apply: $NEW becomes the crontab; read back, compared, the saved list put back on a difference.
apply() {
  local saved stamp
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  saved="crontab.before-road-map-helper.$stamp.$$"
  cp -p "$CURRENT" "$saved"
  if crontab "$NEW" >&2 && crontab -l >"$CHECK" 2>/dev/null && cmp -s "$NEW" "$CHECK"; then
    return 0
  fi
  if [ "$HAD_JOBS" = yes ]; then crontab "$saved" >&2 || true; else crontab -r >&2 || true; fi
  say "road-map helper: WARNING the timed jobs did not read back as written; the earlier list is put back (a copy is $saved)"
  return 1
}

case ${1:-} in
  install)
    case $PWD in *$'\n'*) say "road-map helper: not installed (the install folder's name has a line break)"; exit 1 ;; esac
    read_jobs || { say "road-map helper: not installed (the timed jobs cannot be read: $READ_ERROR)"; exit 1; }
    { without_helper "$CURRENT" "$NEW.tmp" && cat "$NEW.tmp" && helper_line; } >"$NEW"
    rm -f "$NEW.tmp"
    apply || { say "road-map helper: not installed"; exit 1; }
    say "road-map helper: installed (runs every minute)"
    ;;
  uninstall)
    read_jobs || { say "road-map helper: not removed (the timed jobs cannot be read: $READ_ERROR)"; exit 1; }
    if [ "$HAD_JOBS" = no ] || ! has_helper; then say "road-map helper: not installed, nothing to remove"; exit 0; fi
    without_helper "$CURRENT" "$NEW"
    apply || { say "road-map helper: not removed"; exit 1; }
    say "road-map helper: removed"
    ;;
  status)
    read_jobs || { say "road-map helper: cannot tell (the timed jobs cannot be read: $READ_ERROR)"; exit 2; }
    if [ "$HAD_JOBS" = yes ] && has_helper; then
      printf 'road-map helper: installed\n'
    else
      printf 'road-map helper: not installed\n'
      exit 1
    fi
    ;;
  *)
    say "usage: bash scripts/road-map-helper.sh install | uninstall | status"
    exit 2
    ;;
esac
