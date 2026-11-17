# shellcheck shell=bash disable=SC2034 # the variables below are read by the scripts that source this file
# Shared by scripts/deploy.sh (02-05) and scripts/rollback.sh (02-06) on the Pi, sourced from the install dir
# (~/apps/overland-planner). Kept bash-3.2 compatible so the offline tests on macOS run this exact code.
#
# Scope (D99): only compose project `overland`, volume overland_planner-data, images of PLANNER_REPO and files
# under the install dir. Never prune, never touch /etc/docker/daemon.json.

PLANNER_REPO=ghcr.io/mrmilgauss/overland-planner
COMPOSE_PROJECT=overland
DATA_VOLUME=overland_planner-data
# alpine 3.22 manifest list, pinned (tar for the predeploy snapshot, D91).
SNAPSHOT_IMAGE=alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
LOOPBACK=127.0.0.1
WAIT_TIMEOUT=180
# Reason of the last failed check, for releases.log.
FAIL_REASON=

say() { printf '%s\n' "$*" >&2; }

fail() {
  FAIL_REASON=$1
  return 1
}

valid_digest() {
  local hex=${1#sha256:}
  [ "$1" = "sha256:$hex" ] && [ ${#hex} -eq 64 ] || return 1
  case $hex in *[!0-9a-f]*) return 1 ;; esac
}

# env_value FILE KEY: the last KEY=value of a dotenv file (surrounding quotes stripped); the file is never sourced.
env_value() {
  [ -f "$1" ] || return 0
  awk -v key="$2" '
    index($0, key "=") == 1 { value = substr($0, length(key) + 2) }
    END {
      sub(/\r$/, "", value)
      if (value ~ /^".*"$/ || value ~ /^\047.*\047$/) value = substr(value, 2, length(value) - 2)
      print value
    }' "$1"
}

# docker compose for this install: always `-p overland`, .env, then routing.env (06a-ops) and release.env if present.
# routing.env also turns the compose profile `routing` on (valhalla, D239); without it the call is the planner's alone.
planner_compose() {
  local files=(--env-file .env)
  if [ -f routing.env ]; then files+=(--env-file routing.env --profile routing); fi
  if [ -f release.env ]; then files+=(--env-file release.env); fi
  docker compose -p "$COMPOSE_PROJECT" "${files[@]}" "$@"
}

planner_port() {
  local port
  port=$(env_value .env PLANNER_PORT)
  printf '%s\n' "${port:-8080}"
}

# start_routing WHO: bring valhalla to its definition once the planner is published, without --wait. It never changes
# the outcome of the caller: a failure prints one line (D234).
start_routing() {
  [ -f routing.env ] || return 0
  planner_compose up -d valhalla >&2 || say "$1: valhalla did not start (the planner is not affected)"
  return 0
}

# ---- registry access (D196): per-deploy login with the Mac's gh token, nothing stored on the Pi -----------------

REGISTRY=ghcr.io
REGISTRY_USER=MrMilgauss
# Set while docker may hold a ghcr.io login of ours (from the login attempt until a successful logout).
REGISTRY_LOGGED_IN=

# registry_login TOKEN: the token reaches docker on stdin only (printf is a builtin: no argv, no ps).
registry_login() {
  REGISTRY_LOGGED_IN=yes
  printf '%s\n' "$1" | docker login "$REGISTRY" -u "$REGISTRY_USER" --password-stdin >&2
}

# registry_logout: drop docker's ghcr.io login state; a no-op when we never logged in or already logged out.
registry_logout() {
  [ -n "$REGISTRY_LOGGED_IN" ] || return 0
  if docker logout "$REGISTRY" >&2; then
    REGISTRY_LOGGED_IN=
  else
    say "deploy: docker logout $REGISTRY failed; remove the $REGISTRY entry from ~/.docker/config.json by hand"
    return 1
  fi
}

# ---- release pointers (D166, D176) ------------------------------------------------------------------------------

# release.env.prev -> release.env.prev2, release.env -> release.env.prev (whole files: every line kept).
rotate_pointers() {
  if [ -f release.env.prev ]; then cp -p release.env.prev release.env.prev2; fi
  if [ -f release.env ]; then cp -p release.env release.env.prev; fi
}

# write_release FILE IMAGE GIT_SHA COMMIT_TS ALEMBIC_HEAD: rewrite only the four PLANNER_* release keys in place,
# append the missing ones, keep every other line as it is.
write_release() {
  local file=$1 source=$1 tmp="$1.tmp.$$"
  [ -f "$source" ] || source=/dev/null
  awk -v image="$2" -v sha="$3" -v ts="$4" -v head="$5" '
    BEGIN {
      n = split("PLANNER_IMAGE PLANNER_GIT_SHA PLANNER_COMMIT_TS PLANNER_ALEMBIC_HEAD", keys, " ")
      value["PLANNER_IMAGE"] = image; value["PLANNER_GIT_SHA"] = sha
      value["PLANNER_COMMIT_TS"] = ts; value["PLANNER_ALEMBIC_HEAD"] = head
    }
    {
      key = $0; sub(/=.*/, "", key)
      if (index($0, "=") && (key in value)) {
        if (!(key in written)) { print key "=" value[key]; written[key] = 1 }
        next
      }
      print
    }
    END { for (i = 1; i <= n; i++) if (!(keys[i] in written)) print keys[i] "=" value[keys[i]] }
  ' "$source" >"$tmp" && mv "$tmp" "$file"
}

# ---- releases.log (D176: ts, action, digest, git_sha, commit_ts, alembic_head, result, reason), one JSON line ----

json_text() { printf '%s' "$1" | tr '\n\r\t' '   ' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }

# append_release_log ACTION DIGEST GIT_SHA COMMIT_TS ALEMBIC_HEAD RESULT REASON
append_release_log() {
  printf '{"ts":"%s","action":"%s","digest":"%s","git_sha":"%s","commit_ts":"%s","alembic_head":"%s","result":"%s","reason":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(json_text "$1")" "$(json_text "$2")" "$(json_text "$3")" \
    "$(json_text "$4")" "$(json_text "$5")" "$(json_text "$6")" "$(json_text "$7")" >>releases.log
}

# ---- predeploy snapshot (D91, D165): planner stopped, alpine tar of the volume, current + previous kept ----------

# snapshot_volume NAME: snapshots/NAME (a .tgz of overland_planner-data).
snapshot_volume() {
  mkdir -p snapshots
  docker run --rm --network none -v "$DATA_VOLUME:/data:ro" -v "$PWD/snapshots:/backup" "$SNAPSHOT_IMAGE" \
    tar czf "/backup/$1" -C /data .
}

# restore_snapshot NAME: replace the volume content with snapshots/NAME (lossless only before the LAN publish).
restore_snapshot() {
  # shellcheck disable=SC2016 # $1 is expanded by the container's sh
  docker run --rm --network none -v "$DATA_VOLUME:/data" -v "$PWD/snapshots:/backup:ro" "$SNAPSHOT_IMAGE" \
    sh -c 'find /data -mindepth 1 -delete && tar xzf "/backup/$1" -C /data' sh "$1"
}

# Keep the two newest predeploy and the two newest prerollback snapshots (names sort by their UTC timestamp); any
# other file under snapshots/ is never touched.
prune_snapshots() {
  local kind all i
  for kind in predeploy prerollback; do
    all=()
    for i in snapshots/"$kind"-*.tgz; do
      if [ -f "$i" ]; then all+=("$i"); fi
    done
    i=0
    while [ $((i + 2)) -lt ${#all[@]} ]; do
      rm -f "${all[$i]}"
      i=$((i + 1))
    done
  done
}

# ---- start, smoke, publish (D165) -------------------------------------------------------------------------------

# The planner on 127.0.0.1 only (the shell PLANNER_BIND overrides .env): nobody on the LAN can write yet.
start_loopback() {
  PLANNER_BIND=$LOOPBACK planner_compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" planner ||
    fail "loopback start: planner not healthy within ${WAIT_TIMEOUT} s"
}

# curl_planner URL: GET with the household password when .env sets one. The credentials reach curl as a config on
# stdin, so they never appear on a command line (ps) or in the output.
curl_planner() {
  local user password
  user=$(env_value .env PLANNER_BASIC_AUTH_USER)
  password=$(env_value .env PLANNER_BASIC_AUTH_PASSWORD)
  if [ -n "$user" ] && [ -n "$password" ]; then
    printf 'user = "%s:%s"\n' "$(curl_config_text "$user")" "$(curl_config_text "$password")" |
      curl -fsS --max-time 10 -K - "$1"
  else
    curl -fsS --max-time 10 "$1"
  fi
}

curl_config_text() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }

# healthz_ok WHERE URL: /healthz answers {"status":"ok"} (open path, no password needed).
healthz_ok() {
  local body
  body=$(curl -fsS --max-time 10 "$2") || fail "$1: /healthz did not answer 200 at $2" || return 1
  [ "$(printf '%s' "$body" | tr -d ' \n\r')" = '{"status":"ok"}' ] || fail "$1: /healthz answered $body"
}

# The loopback smoke: /healthz ok, /api/health without a fatal component, the last app.started line of this start
# carries app_version == PLANNER_GIT_SHA of release.env.
smoke_loopback() {
  local base body version expected
  base="http://$LOOPBACK:$(planner_port)"
  healthz_ok "loopback smoke" "$base/healthz" || return 1
  body=$(curl_planner "$base/api/health") || fail "loopback smoke: /api/health did not answer 200" || return 1
  body=$(printf '%s' "$body" | tr -d ' \n\r')
  case $body in *'"components":'*) ;; *) fail "loopback smoke: /api/health has no components" || return 1 ;; esac
  case $body in *'"outcome":"fatal"'*) fail "loopback smoke: /api/health reports a fatal component" || return 1 ;; esac
  expected=$(env_value release.env PLANNER_GIT_SHA)
  version=$(planner_compose logs --no-color --no-log-prefix planner 2>/dev/null |
    grep -E '"event": *"app\.started"' | tail -n 1 | sed -nE 's/.*"app_version": *"([^"]*)".*/\1/p')
  if [ -z "$expected" ] || [ "$version" != "$expected" ]; then
    fail "loopback smoke: app.started app_version '$version', expected '$expected'"
  fi
}

# Publish (write gate): recreate with the .env PLANNER_BIND, then smoke on http://PLANNER_BIND:PLANNER_PORT (F-20).
publish() {
  local bind
  bind=$(env_value .env PLANNER_BIND)
  [ -n "$bind" ] || fail "publish: PLANNER_BIND is not set in .env" || return 1
  planner_compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" planner ||
    fail "publish: planner not healthy on $bind" || return 1
  healthz_ok "publish smoke" "http://$bind:$(planner_port)/healthz"
}

# ---- tilesets (06a-ops: make tiles-seed, make spike-cleanup; D92, D166, D178, D237; ADR-013 Amendment 3) -------------

VALHALLA_VOLUME=overland_valhalla-data
VALHALLA_VERSION_WANTED=3.9.1
# default_speeds.json belongs to a tileset: the engine's start script downloads it when it is missing (and the engine has
# no network).
TILES_FILES=(valhalla_tiles.tar admins.sqlite timezones.sqlite valhalla.json default_speeds.json)
# Set by valhalla_status.
VALHALLA_VERSION=
VALHALLA_MODIFIED=

# The tileset files and the spike directory are owned by root: every read of them that needs it, every copy and every
# removal goes through a pinned helper container without network (never sudo).
# dir_sums LABEL DIR: "<sha256>  <name>" of the five tileset files of the host directory DIR (mounted read-only).
dir_sums() {
  # shellcheck disable=SC2016 # "$@" is expanded by the container's sh
  docker run --rm --network none -v "$2:/seed:ro" "$SNAPSHOT_IMAGE" \
    sh -c 'cd /seed && sha256sum "$@"' "$1" "${TILES_FILES[@]}"
}

# volume_sums LABEL SUBDIR: the same listing for SUBDIR (e.g. tilesets/20261101) of the valhalla volume.
volume_sums() {
  # shellcheck disable=SC2016 # "$@" is expanded by the container's sh
  docker run --rm --network none -v "$VALHALLA_VOLUME:/vol:ro" "$SNAPSHOT_IMAGE" \
    sh -c 'cd "/vol/$1" && shift && sha256sum "$@"' "$1" "$2" "${TILES_FILES[@]}"
}

# volume_present_sums LABEL SUBDIR: the listing of the tileset files that SUBDIR holds (a missing file is left out).
volume_present_sums() {
  # shellcheck disable=SC2016 # "$@" is expanded by the container's sh
  docker run --rm --network none -v "$VALHALLA_VOLUME:/vol:ro" "$SNAPSHOT_IMAGE" \
    sh -c 'cd "/vol/$1" && shift && for f in "$@"; do if [ -f "$f" ]; then sha256sum "$f"; fi; done' "$1" "$2" "${TILES_FILES[@]}"
}

# volume_stored_sums SUBDIR: the SHA256SUMS file written at seed time.
volume_stored_sums() {
  # shellcheck disable=SC2016 # $1 is expanded by the container's sh
  docker run --rm --network none -v "$VALHALLA_VOLUME:/vol:ro" "$SNAPSHOT_IMAGE" \
    sh -c 'cat "/vol/$1/SHA256SUMS"' stored-sums "$1"
}

# sums_diff A B: the file names whose "<sha256>  <name>" line is not the same in both listings.
sums_diff() {
  { printf '%s\n' "$1"; printf '%s\n' "$2"; } | sort | uniq -u | awk 'NF > 1 { print $2 }' | sort -u | tr '\n' ' '
}

# valhalla_status: /status of the engine, read from inside the compose network (nothing is published); sets
# VALHALLA_VERSION and VALHALLA_MODIFIED (tileset_last_modified). Fails when it does not answer or has no version.
valhalla_status() {
  local body
  VALHALLA_VERSION=
  VALHALLA_MODIFIED=
  body=$(planner_compose exec -T valhalla curl -fsS --max-time 10 http://127.0.0.1:8002/status) || return 1
  body=$(printf '%s' "$body" | tr -d ' \n\r')
  VALHALLA_VERSION=$(printf '%s' "$body" | sed -nE 's/.*"version":"([^"]*)".*/\1/p')
  VALHALLA_MODIFIED=$(printf '%s' "$body" | sed -nE 's/.*"tileset_last_modified":([0-9]+).*/\1/p')
  [ -n "$VALHALLA_VERSION" ] && [ -n "$VALHALLA_MODIFIED" ]
}

# volume_has_dir SUBDIR: does the valhalla volume hold SUBDIR (e.g. tilesets/20261101)? Exit 0 present, 1 absent, 2 when
# the probe itself failed (docker, the volume): that is "cannot inspect", never "absent".
volume_has_dir() {
  local status=0
  # shellcheck disable=SC2016 # $1 is expanded by the container's sh
  docker run --rm --network none -v "$VALHALLA_VOLUME:/vol:ro" "$SNAPSHOT_IMAGE" \
    sh -c 'test -d "/vol/$1"' tileset-exists "$1" >/dev/null 2>&1 || status=$?
  case $status in 0 | 1) return "$status" ;; *) return 2 ;; esac
}

# logged_modified TILESET: the tileset_last_modified of the last ok or unchanged seed/refresh/rollback line of
# tiles.log for TILESET (what the engine was proven to serve); empty when there is none.
logged_modified() {
  grep -F "\"tileset\":\"$1\"" tiles.log 2>/dev/null | grep -E '"action":"(seed|refresh|rollback)"' |
    grep -E '"result":"(ok|unchanged)"' | tail -n 1 | sed -nE 's/.*"tileset_last_modified":"([^"]*)".*/\1/p'
}

# routing.env (D166): exactly VALHALLA_TILESET=<name>; the previous file stays as routing.env.prev.
# backup_routing keeps both files as they are until discard_routing_backup (success) or restore_routing (failure).
# All three return non-zero when a copy or move failed; a failed backup leaves no copy behind.
backup_routing() {
  local file
  rm -f .routing.env.orig .routing.env.prev.orig
  for file in routing.env routing.env.prev; do
    if [ -f "$file" ] && ! cp -p "$file" ".$file.orig"; then
      rm -f .routing.env.orig .routing.env.prev.orig
      return 1
    fi
  done
}

write_routing() {
  if [ -f routing.env ]; then cp -p routing.env routing.env.prev || return 1; fi
  if ! { printf 'VALHALLA_TILESET=%s\n' "$1" >"routing.env.tmp.$$" && mv "routing.env.tmp.$$" routing.env; }; then
    rm -f "routing.env.tmp.$$"
    return 1
  fi
}

restore_routing() {
  local file status=0
  rm -f routing.env routing.env.prev || status=1
  for file in routing.env routing.env.prev; do
    if [ -f ".$file.orig" ]; then mv ".$file.orig" "$file" || status=1; fi
  done
  return "$status"
}

discard_routing_backup() { rm -f .routing.env.orig .routing.env.prev.orig; }

# ---- tiles.log (ts, action, tileset, tileset_last_modified, result, reason), one JSON line ----------------------

# append_tiles_log ACTION TILESET MODIFIED RESULT REASON
append_tiles_log() {
  printf '{"ts":"%s","action":"%s","tileset":"%s","tileset_last_modified":"%s","result":"%s","reason":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(json_text "$1")" "$(json_text "$2")" "$(json_text "$3")" \
    "$(json_text "$4")" "$(json_text "$5")" >>tiles.log
}
