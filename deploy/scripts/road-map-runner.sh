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
#     ROAD_MAP_PROGRESS=on; a refresh that ended well leaves result.txt state=done and running.txt is removed
# Epoch seconds only: no date is parsed.
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
KEY_PATTERN='^[a-z0-9-]+(/[a-z0-9-]+)?$'
NUMBER_PATTERN='^(0|[1-9][0-9]{0,11})$' # no leading zero: never read as octal
TAB=$(printf '\t')

# ---- the container scripts (expanded by the container's sh) -------------------------------------------------------------

# shellcheck disable=SC2016
SEEN_SH='cd /vol || exit 3
[ -L helper-seen ] && rm -f helper-seen
touch helper-seen'

# MODE read | take: the first line is the state (busy, gone, none, refused, ok), then the capped bytes of the file.
# take renames request.txt to running.txt first: the rename fails when the planner cancelled it a moment ago.
# shellcheck disable=SC2016
READ_SH='cd /vol || exit 3
case $1 in
  read)
    if [ -e running.txt ] || [ -L running.txt ]; then echo busy; exit 0; fi
    name=request.txt ;;
  take)
    mv request.txt running.txt 2>/dev/null || { echo gone; exit 0; }
    name=running.txt ;;
  *) exit 2 ;;
esac
if [ -L "$name" ]; then echo refused; exit 0; fi
if [ ! -e "$name" ]; then echo none; exit 0; fi
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
printf "%s\n" "$1" >.result.tmp && mv .result.tmp result.txt && rm -f running.txt'

# A request taken a moment before the planner replaced it by one that is not due: put it back (or drop it, a newer one is there).
# shellcheck disable=SC2016
RETURN_SH='cd /vol || exit 3
if [ -e request.txt ]; then rm -f running.txt; else mv running.txt request.txt; fi'

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

# validate_request TEXT: exactly the lines the planner writes. Sets START_AT (empty: none) and REGION_LINES.
START_AT=
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
        requested=yes ;;
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
  [ "$requested" = yes ] && [ "$added" = yes ] && [ "$removed" = yes ]
}

# due: no start time, or the time has come.
due() { [ -z "$START_AT" ] || [ "$START_AT" -le "$(date +%s)" ]; }

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
  changes_run "$REFUSE_SH" refuse-request "$(printf 'finished_at=%s\nstate=failed\ncode=bad_request' "$(date +%s)")" >&2 ||
    say "road-map-runner: the refusal could not be written"
  exit 0
}

# ---- one run ------------------------------------------------------------------------------------------------------------

changes_run "$SEEN_SH" helper-seen >&2 || {
  say "road-map-runner: the changes folder cannot be reached; nothing was done"
  exit 0
}

exec 8>>.road-map-runner.lock
flock -n 8 || exit 0

read_request read || {
  say "road-map-runner: the request could not be read; nothing was done"
  exit 0
}
case $STATE in
  none | busy) exit 0 ;;
  refused) refuse ;;
  ok) ;;
  *) say "road-map-runner: unexpected answer '$STATE'; nothing was done"; exit 0 ;;
esac
validate_request "$BODY" || refuse
due || exit 0

read_request take || {
  say "road-map-runner: the request could not be taken; nothing was done"
  exit 0
}
case $STATE in
  gone | none) exit 0 ;; # the planner cancelled it a moment ago: the rename lost
  refused) refuse ;;
  ok) ;;
  *) say "road-map-runner: unexpected answer '$STATE'; nothing was done"; exit 0 ;;
esac
validate_request "$BODY" || refuse
if ! due; then
  changes_run "$RETURN_SH" return-request >&2
  exit 0
fi

REGIONS_FILE=$(mktemp "$PWD/.road-map-regions.XXXXXX") || {
  say "road-map-runner: no temporary file; nothing was done"
  exit 0
}
trap 'rm -f "$REGIONS_FILE"' EXIT
chmod 600 "$REGIONS_FILE"
printf '%s\n' "$REGION_LINES" >"$REGIONS_FILE"
export REGIONS_FILE
ROAD_MAP_PROGRESS=on bash scripts/tiles-refresh.sh >&2
status=$?
if [ "$status" -eq 0 ]; then
  changes_run "$FINISH_SH" finish-request "$(printf 'finished_at=%s\nstate=done\n%s' "$(date +%s)" "$BODY")" >&2 ||
    say "road-map-runner: the result could not be written"
else
  say "road-map-runner: the refresh ended with status $status"
fi
exit 0
