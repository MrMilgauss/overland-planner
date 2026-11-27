#!/usr/bin/env bash
# The road-map helper's timed job (D303, D304, D314, D315, D316; ADR-013 Amendment 5): one run a minute from the deploy
# user's crontab, `cd <install dir> && bash scripts/road-map-runner.sh`. It takes the owner's request at its time,
# validates it strictly and starts the refresh on the regions the request names.
#
# The changes folder is the volume overland_road-map, one writer per file: the planner writes request.txt and
# cancelled.txt; this script writes helper-seen, running.txt, result.txt (the refresh writes progress.txt and failure.txt).
# Every touch of the volume is one short `docker run` of the pinned image (lib.sh changes_run: no network, uid 10001, no
# capabilities, read-only root, caps, at most 60 s) that mounts only that volume, never the served map. Files that are not
# plain are refused and never read, reads are capped (the request 64 KB), and nothing read is evaluated or sourced: the
# container prints the capped bytes, this script validates them line by line against fixed patterns.
#   1 helper-seen is touched on every run, before the lock is looked at (the planner's sign that the helper lives)
#   2 its own lock (.road-map-runner.lock, never .deploy.lock: the refresh takes that one itself); held: leave at once
#   3 request.txt: none -> nothing to do; running.txt exists -> a rebuild is recorded, leave it; not a plain file, over
#     64 KB or not valid -> result.txt state=failed code=bad_request, request.txt removed, nothing runs
#   4 start_at in the future -> left alone; else the request is taken by renaming request.txt to running.txt (the
#     planner cancels by renaming the same file: the rename that wins decides), read again and validated again
#   5 the regions file (mode 600, six tab-separated fields per line) is written and tiles-refresh.sh runs on it with
#     ROAD_MAP_PROGRESS=on (its own output goes to .road-map-refresh.out, never to the log); then
#       exit 0   result.txt state=done, running.txt removed
#       exit 75  the Pi was busy (.deploy.lock): running.txt goes back to request.txt, unchanged, and the next minute
#                tries again; the first 75 is kept in locked-since.txt (this script's own file, epoch seconds) and after
#                30 minutes the end is state=failed code=locked
#       other    state=failed with the code and the numbers the refresh left in failure.txt (read line by line against
#                fixed patterns; none or not valid: code=interrupted); the request lines are kept in result.txt
#   6 recovery (D314): a running.txt that nobody holds (this script holds its own lock, so the refresh that wrote it is
#     gone) while .deploy.lock is free (flock -n; held: nothing is touched, the next minute tries again): valhalla is
#     brought up under a timeout, then routing.env's VALHALLA_TILESET is compared with new= of progress.txt. Pointers change
#     only at the switch: equal and healthy -> state=done; different -> state=failed code=interrupted (the old map serves).
#     Equal but the engine does not answer: nothing is decided, the next minute tries again. The refresh's restore logic
#     never runs here. A leftover .routing.env.orig (a switch cut in half) is only named in the log, never moved (D314).
# road-map-runner.log gets one line per state change (taken, busy, done, failed, recovered), never one for an idle minute,
# and is cut to its last 200 lines when it passes 64 KB.
# Epoch seconds only: no date is parsed. ROAD_MAP_NOW (epoch seconds) replaces the clock in the offline tests.
set -uo pipefail

# cron's PATH is short: the standard places come after whatever is already there
PATH=$PATH:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
export LC_ALL=C # lengths are bytes, [[:cntrl:]] is the ASCII controls

cd "$(dirname "$0")/.." || exit 1
# shellcheck source=deploy/scripts/lib.sh disable=SC1091 # followed by make lint-ci; the pre-commit hook gets no -x
. scripts/lib.sh

MAX_REGIONS=40
MAX_LINES=50
MAX_NOTE=4096
LOCKED_AFTER=1800 # a Pi busy this long for the refresh is a failed rebuild (code=locked)
LOG=road-map-runner.log
KEY_PATTERN='^[a-z0-9-]+(/[a-z0-9-]+)?$'
NUMBER_PATTERN='^(0|[1-9][0-9]{0,11})$' # no leading zero: never read as octal
TAB=$(printf '\t')

# ---- the container scripts (expanded by the container's sh) -------------------------------------------------------------

# shellcheck disable=SC2016
SEEN_SH='cd /vol || exit 3
[ -L helper-seen ] && rm -f helper-seen
touch helper-seen'

# MODE read | running | take: the first line is the state (busy, gone, none, refused, ok), then the capped bytes of the file.
# take renames request.txt to running.txt first: the rename fails when the planner cancelled it a moment ago.
# shellcheck disable=SC2016
READ_SH='cd /vol || exit 3
case $1 in
  read)
    if [ -e running.txt ] || [ -L running.txt ]; then echo busy; exit 0; fi
    name=request.txt ;;
  running) name=running.txt ;;
  take)
    # no running.txt exists here, so the notes belong to an ended rebuild; they go before the rename so that a cut between the
    # two never leaves them beside the running one, where recovery would read them
    rm -f progress.txt failure.txt
    mv request.txt running.txt 2>/dev/null || { echo gone; exit 0; }
    name=running.txt ;;
  *) exit 2 ;;
esac
if [ -L "$name" ]; then echo refused; exit 0; fi
if [ ! -e "$name" ]; then
  [ "$name" = request.txt ] && rm -f locked-since.txt # no request waits: no busy minute counts for the next one
  echo none; exit 0
fi
if [ ! -f "$name" ]; then echo refused; exit 0; fi
size=$(head -c 65537 "$name" | wc -c)
if [ "$size" -gt 65536 ]; then echo refused; exit 0; fi
if [ "$(head -c 65537 "$name" | tr -d "\000" | wc -c)" -ne "$size" ]; then echo refused; exit 0; fi
echo ok
head -c 65536 "$name"'

# The result text is the argument; the request is removed first, so a refused one is never looked at again.
# shellcheck disable=SC2016
REFUSE_SH='cd /vol || exit 3
rm -rf -- request.txt running.txt
printf "%s\n" "$1" >.result.tmp && mv .result.tmp result.txt'

# shellcheck disable=SC2016
FINISH_SH='cd /vol || exit 3
printf "%s\n" "$1" >.result.tmp && mv .result.tmp result.txt && rm -f running.txt failure.txt locked-since.txt'

# One of the notes the refresh and this script keep (failure.txt, progress.txt, locked-since.txt): a plain file, 4 KB read at most.
# shellcheck disable=SC2016
NOTE_SH='cd /vol || exit 3
[ -f "$1" ] && [ ! -L "$1" ] || exit 0
head -c 4097 "$1"'

# shellcheck disable=SC2016
SET_NOTE_SH='cd /vol || exit 3
printf "%s\n" "$2" >".$1.tmp" && mv ".$1.tmp" "$1"'

# A request taken a moment before the planner replaced it by one that is not due: put it back (or drop it, a newer one is there).
# shellcheck disable=SC2016
RETURN_SH='cd /vol || exit 3
if [ -e request.txt ]; then rm -f running.txt locked-since.txt; else mv running.txt request.txt; fi'

# ---- validation ---------------------------------------------------------------------------------------------------------

PREFIX=$(env_value .env ROAD_MAP_DOWNLOAD_PREFIX)
PREFIX=${PREFIX:-https://download.geofabrik.de/}
case $PREFIX in */) ;; *) PREFIX=$PREFIX/ ;; esac

# plain_text VALUE MAX: printable UTF-8, no control character (a tab is one), at most MAX bytes.
plain_text() {
  [ "${#1}" -le "$2" ] || return 1
  case $1 in *[[:cntrl:]]*) return 1 ;; esac
  printf '%s' "$1" | iconv -f UTF-8 -t UTF-8 >/dev/null 2>&1
}

# address_ok ADDRESS FILE: under the download prefix, no .., only the characters of a plain address, and the file is the
# one of the region the line names (an address of another region is not this region's).
address_ok() {
  case $1 in "$PREFIX"?*) ;; *) return 1 ;; esac
  case $1 in *..* | *[!A-Za-z0-9._/:-]*) return 1 ;; esac
  [ "${1##*/}" = "$2" ]
}

# region_ok FIELDS: key, name, parent name, .osm.pbf address, .poly address, bytes, tab-separated (six fields exactly).
region_ok() {
  local rest=$1 key name parent pbf poly bytes tabs
  tabs=${rest//[!"$TAB"]/}
  [ "${#tabs}" -eq 5 ] || return 1
  key=${rest%%"$TAB"*} rest=${rest#*"$TAB"}
  name=${rest%%"$TAB"*} rest=${rest#*"$TAB"}
  parent=${rest%%"$TAB"*} rest=${rest#*"$TAB"}
  pbf=${rest%%"$TAB"*} rest=${rest#*"$TAB"}
  poly=${rest%%"$TAB"*} bytes=${rest#*"$TAB"}
  [[ $key =~ $KEY_PATTERN ]] || return 1
  case " $SEEN_KEYS " in *" $key "*) return 1 ;; esac
  SEEN_KEYS="$SEEN_KEYS $key"
  [ -n "$name" ] && plain_text "$name" 120 || return 1
  [ -z "$parent" ] || plain_text "$parent" 120 || return 1
  address_ok "$pbf" "${key##*/}-latest.osm.pbf" && address_ok "$poly" "${key##*/}.poly" || return 1
  [[ $bytes =~ $NUMBER_PATTERN ]]
}

# validate_request TEXT: exactly the lines the planner writes. Sets START_AT (empty: none), REQUESTED_AT and REGION_LINES.
START_AT=
REQUESTED_AT=
REGION_LINES=
SEEN_KEYS=
validate_request() {
  local line count=0 regions=0 requested=no added=no removed=no started=no
  START_AT='' REGION_LINES='' SEEN_KEYS=''
  while IFS= read -r line; do
    count=$((count + 1))
    [ "$count" -le "$MAX_LINES" ] || return 1
    if [ "$count" -eq 1 ]; then
      [ "$line" = schema=1 ] || return 1
      continue
    fi
    case $line in
      requested_at=*)
        [ "$requested" = no ] && [[ ${line#*=} =~ $NUMBER_PATTERN ]] || return 1
        requested=yes REQUESTED_AT=${line#*=} ;;
      start_at=*)
        [ "$started" = no ] && [[ ${line#*=} =~ $NUMBER_PATTERN ]] || return 1
        started=yes START_AT=${line#*=} ;;
      added=*)
        [ "$added" = no ] && plain_text "${line#*=}" "$MAX_NOTE" || return 1
        added=yes ;;
      removed=*)
        [ "$removed" = no ] && plain_text "${line#*=}" "$MAX_NOTE" || return 1
        removed=yes ;;
      region=*)
        regions=$((regions + 1))
        [ "$regions" -le "$MAX_REGIONS" ] && region_ok "${line#*=}" || return 1
        REGION_LINES="${REGION_LINES:+$REGION_LINES
}${line#*=}" ;;
      *) return 1 ;;
    esac
  done <<<"$1"
  [ "$requested" = yes ] && [ "$added" = yes ] && [ "$removed" = yes ] && [ "$regions" -ge 1 ]
}

now() { printf '%s' "${ROAD_MAP_NOW:-$(date +%s)}"; }

# due: no start time, or the time has come.
due() { [ -z "$START_AT" ] || [ "$START_AT" -le "$(now)" ]; }

# log_state WORDS: one line per state change; past 64 KB the file is cut to its last 200 lines in place (the cron redirect
# holds the file open in append mode, so the inode stays).
log_state() {
  local size
  printf '%s %s\n' "$(now)" "$*" >>"$LOG" 2>/dev/null || return 0
  size=$(wc -c <"$LOG")
  if [ $((size + 0)) -gt 65536 ]; then
    tail -n 200 "$LOG" >"$LOG.tmp" && cat "$LOG.tmp" >"$LOG"
    rm -f "$LOG.tmp"
  fi
}

# note NAME: the text of a note of the changes folder, empty when it is none, not plain or over 4 KB.
note() {
  local text
  text=$(changes_run "$NOTE_SH" read-note "$1") || return 0
  [ "${#text}" -le "$MAX_NOTE" ] && printf '%s' "$text"
}

# failure_note: FAIL_CODE and FAIL_FACTS (lines) from failure.txt: code= once and free_gb= need_gb= have_gb= at most once
# each, numbers only; anything else and the whole note is ignored (code=interrupted: the refresh left no word).
FAIL_CODE=
FAIL_FACTS=
failure_note() {
  local line code='' facts='' seen=' '
  FAIL_CODE=interrupted FAIL_FACTS=
  while IFS= read -r line; do
    case $line in
      code=*)
        [ -z "$code" ] && [[ ${line#*=} =~ ^[a-z_]{1,32}$ ]] || return 0
        code=${line#*=} ;;
      free_gb=* | need_gb=* | have_gb=*)
        case $seen in *" ${line%%=*} "*) return 0 ;; esac
        [[ ${line#*=} =~ ^[0-9]{1,6}$ ]] || return 0
        seen="$seen${line%%=*} " facts="${facts:+$facts
}$line" ;;
      '') ;;
      *) return 0 ;;
    esac
  done <<<"$(note failure.txt)"
  [ -z "$code" ] || { FAIL_CODE=$code FAIL_FACTS=$facts; }
}

# progress_new: new= of progress.txt when it is a tileset name the planner reads (its _TILESET pattern), else empty.
progress_new() {
  local line new=
  while IFS= read -r line; do
    case $line in new=*) [ -n "$new" ] || new=${line#*=} ;; esac
  done <<<"$(note progress.txt)"
  [[ $new =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$ ]] && printf '%s' "$new"
  return 0
}

# finish_done [TILESET]: state=done with the map that was made (the planner shows "ended well" only when it serves it).
finish_done() {
  finish "state=done${1:+
tileset=$1}"
}

# finish STATE_LINES: result.txt (finished_at, the state lines, the request lines of BODY) and running.txt removed.
finish() {
  changes_run "$FINISH_SH" finish-request "$(printf 'finished_at=%s\n%s%s' "$(now)" "$1" "${BODY:+
$BODY}")" >&2 ||
    say "road-map-runner: the result could not be written"
}

finish_failed() { # CODE [FACT_LINES]
  finish "state=failed
code=$1${2:+
$2}"
}

# read_request MODE: STATE (the container's first line) and BODY (the capped bytes); non-zero when the container failed.
STATE=
BODY=
read_request() {
  local out
  out=$(changes_run "$READ_SH" "$1-request" "$1") || return 1
  STATE=${out%%$'\n'*}
  case $out in *$'\n'*) BODY=${out#*$'\n'} ;; *) BODY= ;; esac
}

refuse() {
  say "road-map-runner: the request is not what the planner writes; refused"
  changes_run "$REFUSE_SH" refuse-request "$(printf 'finished_at=%s\nstate=failed\ncode=bad_request' "$(now)")" >&2 ||
    say "road-map-runner: the refusal could not be written"
  exit 0
}

# ---- the busy Pi and the rebuild the Pi lost ----------------------------------------------------------------------------

# busy_pi: the refresh found .deploy.lock held (75): the request goes back for the next minute, until the first 75 is 30
# minutes old.
busy_pi() {
  local at since
  at=$(now)
  since=$(note locked-since.txt)
  since=${since%%$'\n'*}
  # a first busy minute older than the request is the note of an earlier request (cancelled before this one was made)
  if ! { [[ $since =~ $NUMBER_PATTERN ]] && [ "$since" -le "$at" ] && [ "$since" -ge "${REQUESTED_AT:-0}" ]; }; then
    since=$at
    changes_run "$SET_NOTE_SH" set-note locked-since.txt "$at" >&2 || say "road-map-runner: locked-since.txt could not be written"
  fi
  if [ $((at - since)) -ge "$LOCKED_AFTER" ]; then
    finish_failed locked
    log_state "failed code=locked"
    return 0
  fi
  changes_run "$RETURN_SH" return-request >&2
  log_state busy
}

# engine_healthy: /status answers, asked up to 12 times (ROAD_MAP_POLL seconds apart, default 5).
engine_healthy() {
  local i
  # shellcheck disable=SC2034 # a counter only
  for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    COMPOSE_TIMEOUT=30 valhalla_status >/dev/null 2>&1 && return 0
    sleep "${ROAD_MAP_POLL:-5}"
  done
  return 1
}

# recover: running.txt is there and nobody holds this script's lock: the refresh that wrote it is gone.
recover() {
  local new serving
  exec 9>>.deploy.lock
  flock -n 9 || exit 0 # a deploy, rollback or tiles run holds it: nothing is touched, the next minute tries again
  read_request running || exit 0
  case $STATE in
    ok) validate_request "$BODY" || BODY= ;;
    refused) BODY= ;;
    *) exit 0 ;;
  esac
  if [ -e .routing.env.orig ]; then say "road-map-runner: .routing.env.orig is left by a switch cut in half; not touched"; fi
  COMPOSE_TIMEOUT=120 planner_compose up -d valhalla >&2 || say "road-map-runner: valhalla did not start in time"
  new=$(progress_new)
  serving=$(env_value routing.env VALHALLA_TILESET)
  if [ -n "$new" ] && [ "$new" = "$serving" ]; then
    engine_healthy || {
      say "road-map-runner: the new map is named but the engine does not answer; the next minute tries again"
      exit 0
    }
    finish_done "$new"
    log_state "recovered done"
  else
    finish_failed interrupted
    log_state "recovered failed code=interrupted"
  fi
  exit 0
}

# nothing_done WHY: the run stops without touching anything; the next minute tries again.
nothing_done() {
  say "road-map-runner: $1; nothing was done"
  exit 0
}

# ---- one run ------------------------------------------------------------------------------------------------------------

changes_run "$SEEN_SH" helper-seen >&2 || nothing_done "the changes folder cannot be reached"

exec 8>>.road-map-runner.lock
flock -n 8 || exit 0

read_request read || nothing_done "the request could not be read"
case $STATE in
  none) exit 0 ;;
  busy) recover ;;
  refused) refuse ;;
  ok) ;;
  *) nothing_done "unexpected answer '$STATE'" ;;
esac
validate_request "$BODY" || refuse
due || exit 0

read_request take || nothing_done "the request could not be taken"
case $STATE in
  gone | none) exit 0 ;; # the planner cancelled it a moment ago: the rename lost
  refused) refuse ;;
  ok) ;;
  *) nothing_done "unexpected answer '$STATE'" ;;
esac
validate_request "$BODY" || refuse
if ! due; then
  changes_run "$RETURN_SH" return-request >&2
  exit 0
fi

REGIONS_FILE=$(mktemp "$PWD/.road-map-regions.XXXXXX") || nothing_done "no temporary file"
trap 'rm -f "$REGIONS_FILE"' EXIT
chmod 600 "$REGIONS_FILE"
printf '%s\n' "$REGION_LINES" >"$REGIONS_FILE"
export REGIONS_FILE
log_state taken
ROAD_MAP_PROGRESS=on bash scripts/tiles-refresh.sh >.road-map-refresh.out 2>&1
status=$?
case $status in
  0)
    new=$(progress_new)
    finish_done "$new"
    if [ -n "$new" ]; then log_state "done"; else log_state "done without a tileset name"; fi ;;
  75) busy_pi ;;
  *)
    failure_note
    finish_failed "$FAIL_CODE" "$FAIL_FACTS"
    log_state "failed code=$FAIL_CODE" ;;
esac
exit 0
