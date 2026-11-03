#!/usr/bin/env bash
# make pi-preflight (D99, D178): read-only checks on pi-host before a deploy, streamed over ssh
# (`ssh PI_HOST 'bash -s -- PI_DIR' < deploy/scripts/pi-preflight.sh`), so it works before the first deploy.
# Never changes anything, never prints a secret (.env values other than PLANNER_BIND/PLANNER_PORT, registry auth).
#
#   port 8080 on PLANNER_BIND free, or published by compose project overland
#   disk free under the install dir >= 5 GB      MemAvailable >= 1 GB
#   the compose projects already on the Pi (ours is `overland`; another stack is left alone)
#   .env present with PLANNER_BIND               registry access: per-deploy login (D196), so no stored ghcr.io
#                                                login is expected (WARN if one exists; credentials never shown)
#
# Usage: pi-preflight.sh [INSTALL_DIR]   (default apps/overland-planner, relative to $HOME)
# Exit 0 when every check passes, 1 otherwise. MEMINFO overrides /proc/meminfo (offline tests only).
set -uo pipefail

dir=${1:-apps/overland-planner}
cd "$HOME" 2>/dev/null || true
problems=0

ok() { printf 'ok    %s\n' "$*"; }
bad() {
  printf 'FAIL  %s\n' "$*"
  problems=$((problems + 1))
}

env_key() { [ -f "$dir/.env" ] && sed -n "s/^$1=//p" "$dir/.env" | tail -n 1; }

if [ -f "$dir/.env" ]; then
  bind=$(env_key PLANNER_BIND)
  if [ -n "$bind" ]; then ok ".env present, PLANNER_BIND=$bind"; else bad ".env has no PLANNER_BIND (e.g. 192.168.1.10)"; fi
else
  bind=
  bad "$dir/.env missing (copy deploy/.env.example and set PLANNER_BIND)"
fi
port=$(env_key PLANNER_PORT)
port=${port:-8080}

listeners=$(ss -ltnH "sport = :$port" 2>/dev/null)
ours=$(docker ps --filter label=com.docker.compose.project=overland --format '{{.Ports}}' 2>/dev/null)
if [ -z "$listeners" ]; then
  ok "port $port free"
elif printf '%s' "$ours" | grep -q ":$port->"; then
  ok "port $port published by compose project overland"
else
  bad "port $port is taken by something else: $(printf '%s' "$listeners" | tr '\n' ' ')${bind:+(planner bind $bind)}"
fi

free_kb=$(df -Pk "${dir%/*}" 2>/dev/null | awk 'NR == 2 { print $4 }')
if [ "${free_kb:-0}" -ge $((5 * 1024 * 1024)) ]; then
  ok "disk: $((free_kb / 1024 / 1024)) GB free"
else
  bad "disk: only $((${free_kb:-0} / 1024)) MB free (need 5 GB)"
fi

available_kb=$(awk '$1 == "MemAvailable:" { print $2 }' "${MEMINFO:-/proc/meminfo}" 2>/dev/null)
if [ "${available_kb:-0}" -ge $((1024 * 1024)) ]; then
  ok "MemAvailable: $((available_kb / 1024)) MB"
else
  bad "MemAvailable: $((${available_kb:-0} / 1024)) MB (need 1 GB)"
fi

if projects=$(docker compose ls --all --quiet 2>/dev/null); then
  ok "compose projects: $(printf '%s' "${projects:-none}" | tr '\n' ' ')(ours: overland)"
else
  bad "docker compose ls failed: is docker running and the deploy user in the docker group?"
fi

if grep -q '"ghcr.io"' "$HOME/.docker/config.json" 2>/dev/null; then
  printf 'WARN  registry access: per-deploy login (D196), but a ghcr.io login is stored in ~/.docker/config.json;'
  printf ' remove that entry (deploys log in and out by themselves)\n'
else
  ok "registry access: per-deploy login (D196)"
fi

if [ "$problems" -gt 0 ]; then
  printf 'pi-preflight: %s check(s) failed\n' "$problems"
  exit 1
fi
printf 'pi-preflight: all checks passed\n'
