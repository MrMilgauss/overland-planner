#!/usr/bin/env bash
# `make deploy [SHA=<git sha>]` on the Mac (D88, D89, D176, D195). Never runs on the Pi.
#
#  1 clean working tree
#  2 SHA: the given one, or the newest main SHA whose ci.yml run succeeded and has a release.json artifact
#  3 the SHA has a successful ci.yml push run on main (the only gate, D88); its release.json is downloaded (gh)
#  4 verify_provenance.py: release.json names the SHA, and the image's buildx provenance names this repository at
#    that SHA on linux/amd64 and linux/arm64 (fail closed)
#  5 read-only ssh preflight: the Pi has .env with PLANNER_BIND
#  6 rsync deploy/ (never .env, release pointers, releases.log or snapshots; no --delete)
#  7 ssh scripts/deploy.sh <digest> with `gh auth token` on its stdin (D196: the Pi stores no registry credential;
#    the token is never on a command line or in a file); copy releases.log back to .data/ops/releases.log
set -uo pipefail

PI_HOST=${PI_HOST:-}
PI_DIR=${PI_DIR:-}
PLANNER_URL=${PLANNER_URL:-}
SHA=${1:-}

cd "$(dirname "$0")/../.." || exit 1

die() {
  printf 'make deploy: %s\n' "$*" >&2
  exit 1
}

# The Pi's address is not in git (deploy/pi.env.example). A variable already in the environment wins over the file.
PI_ENV_FILE=${PI_ENV_FILE:-deploy/pi.env}
if [ -f "$PI_ENV_FILE" ]; then
  while IFS='=' read -r key value; do
    case $key in
      PI_HOST | PI_DIR | PLANNER_URL) [ -n "${!key:-}" ] || printf -v "$key" '%s' "$value" ;;
    esac
  done <"$PI_ENV_FILE"
fi
PI_DIR=${PI_DIR:-apps/overland-planner}
[ -n "$PI_HOST" ] || die "set PI_HOST (see deploy/pi.env.example)"

[ -z "$(git status --porcelain)" ] || die "working tree not clean; commit or stash first"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
run_id=
if [ -z "$SHA" ]; then
  candidates=$(gh run list --workflow ci.yml --branch main --event push --status success --limit 20 \
    --json databaseId,headSha --jq '.[] | "\(.databaseId) \(.headSha)"') || die "gh run list failed"
  while read -r id sha; do
    [ -n "$id" ] || continue
    if gh run download "$id" --name release.json --dir "$work/$id" >/dev/null 2>&1; then
      run_id=$id
      SHA=$sha
      break
    fi
  done <<EOF
$candidates
EOF
  [ -n "$run_id" ] || die "no successful ci.yml run on main has a release.json artifact"
else
  run_id=$(gh run list --workflow ci.yml --branch main --event push --status success --commit "$SHA" --limit 1 \
    --json databaseId --jq '.[0].databaseId // empty') || die "gh run list failed"
  [ -n "$run_id" ] || die "no successful ci.yml run on main for $SHA"
  gh run download "$run_id" --name release.json --dir "$work/$run_id" >/dev/null ||
    die "successful run $run_id of $SHA has no release.json artifact"
fi

digest=$(python3 deploy/scripts/verify_provenance.py --release-json "$work/$run_id/release.json" --sha "$SHA") ||
  die "refusing to deploy $SHA: provenance check failed"

# shellcheck disable=SC2029 # PI_DIR is meant to expand on the Mac
ssh -o BatchMode=yes "$PI_HOST" "cd $PI_DIR && test -f .env && grep -Eq '^PLANNER_BIND=[^[:space:]]+' .env" ||
  die "the Pi has no ~/$PI_DIR/.env with PLANNER_BIND set; create it from .env.example (mode 600) first"

token=$(gh auth token 2>/dev/null) && [ -n "$token" ] ||
  die "gh is not logged in — run: gh auth login -h github.com -s read:packages"

rsync -a --exclude=.env --exclude='release.env*' --exclude=releases.log --exclude=snapshots/ \
  --exclude=.deploy.lock --exclude='routing.env*' --exclude=__pycache__/ \
  deploy/ "$PI_HOST:$PI_DIR/" || die "rsync to $PI_HOST failed"

status=0
# shellcheck disable=SC2029 # expanded on the Mac on purpose
printf '%s\n' "$token" | ssh -o BatchMode=yes "$PI_HOST" "cd $PI_DIR && bash scripts/deploy.sh $digest" || status=$?
token=

mkdir -p .data/ops
if rsync -a "$PI_HOST:$PI_DIR/releases.log" .data/ops/releases.log; then
  tail -n 3 .data/ops/releases.log 2>/dev/null
else
  printf 'make deploy: could not copy releases.log back\n' >&2
fi
[ "$status" -eq 0 ] || die "deploy of $SHA ($digest) failed on the Pi (exit $status); see releases.log"
printf 'Deployed %s (%s): %s\n' "$SHA" "$digest" "$PLANNER_URL"
