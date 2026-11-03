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
planner_compose() {
  local files=(--env-file .env)
  if [ -f routing.env ]; then files+=(--env-file routing.env); fi
  if [ -f release.env ]; then files+=(--env-file release.env); fi
  docker compose -p "$COMPOSE_PROJECT" "${files[@]}" "$@"
}

planner_port() {
  local port
  port=$(env_value .env PLANNER_PORT)
  printf '%s\n' "${port:-8080}"
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

# Keep the two newest predeploy snapshots (names sort by their UTC timestamp).
prune_snapshots() {
  local all=() i
  for i in snapshots/predeploy-*.tgz; do
    if [ -f "$i" ]; then all+=("$i"); fi
  done
  i=0
  while [ $((i + 2)) -lt ${#all[@]} ]; do
    rm -f "${all[$i]}"
    i=$((i + 1))
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
