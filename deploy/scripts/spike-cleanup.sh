#!/usr/bin/env bash
# Remove the SPIKE-2R directory ~/valhalla-spike once the seeded tileset is proven (D92, D178, D237). Run by
# `make spike-cleanup`, which asks for the typed confirmation on the Mac between the two calls:
#
#   cd ~/apps/overland-planner && bash scripts/spike-cleanup.sh check     # every guard, removes nothing
#   cd ~/apps/overland-planner && bash scripts/spike-cleanup.sh delete    # the same guards, then the removal
#
# The target is the literal $HOME/valhalla-spike: no argument or glob can change it. Refused (exit 1, nothing
# removed) unless: it is a real directory and no symlink; valhalla answers /status on the tileset of routing.env;
# the sha256 of the four originals, recomputed now, equal SHA256SUMS of the seed and the recomputed seeded copies.
# The files are root-owned: the removal runs in the pinned helper container (--network none), never with sudo.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
# shellcheck source=deploy/scripts/lib.sh
. scripts/lib.sh

MODE=${1:-check}
TARGET="$HOME/valhalla-spike"
TILESET=
MODIFIED=

record() { append_tiles_log spike-cleanup "$TILESET" "$MODIFIED" "$1" "${2:-}"; }

refuse() {
  say "spike-cleanup: refused: $1; nothing removed"
  record refused "$1"
  exit 1
}

# partly WHY: the removal started and did not finish, so "nothing removed" would be false.
partly() {
  say "spike-cleanup: $1; removal failed part-way; ~/valhalla-spike may be partly removed"
  record failed "$1; removal failed part-way; ~/valhalla-spike may be partly removed"
  exit 1
}

case $MODE in
  check | delete) ;;
  *)
    say "usage: scripts/spike-cleanup.sh [check|delete]"
    exit 2
    ;;
esac

# 1. The target is exactly $HOME/valhalla-spike, a real directory.
if [ -L "$TARGET" ] || [ ! -d "$TARGET" ]; then refuse "$TARGET is not a real directory (missing or a symlink)"; fi
home_physical=$(cd -P "$HOME" && pwd -P) || refuse "cannot resolve $HOME"
resolved=$(cd -P "$TARGET" && pwd -P) || refuse "cannot resolve $TARGET"
if [ "$resolved" != "$home_physical/valhalla-spike" ]; then refuse "$TARGET resolves to $resolved"; fi

# 2. Valhalla is healthy on the tileset of routing.env.
TILESET=$(env_value routing.env VALHALLA_TILESET)
[ -n "$TILESET" ] || refuse "routing.env names no tileset: run make tiles-seed first"
logged=$(logged_modified "$TILESET")
valhalla_status || refuse "valhalla does not answer /status"
MODIFIED=$VALHALLA_MODIFIED
if [ -z "$logged" ] || [ "$VALHALLA_MODIFIED" != "$logged" ]; then
  refuse "valhalla serves tileset_last_modified '$VALHALLA_MODIFIED', tiles.log recorded '$logged' for $TILESET"
fi

# 3. Originals, seed-time SHA256SUMS and seeded copies all agree (recomputed now).
say "spike-cleanup: checksums of the originals and of the seeded copy (this takes a while)"
originals=$(dir_sums source-sums "$TARGET/custom_files") || refuse "cannot read the originals in $TARGET/custom_files"
stored=$(volume_stored_sums "tilesets/$TILESET") || refuse "tilesets/$TILESET has no SHA256SUMS"
copies=$(volume_sums tileset-sums "tilesets/$TILESET") || refuse "cannot read the seeded copy tilesets/$TILESET"
if [ "$originals" != "$stored" ]; then
  refuse "the originals differ from the SHA256SUMS of the seed: $(sums_diff "$originals" "$stored")"
fi
if [ "$originals" != "$copies" ]; then
  refuse "the originals differ from the seeded copy: $(sums_diff "$originals" "$copies")"
fi

if [ "$MODE" = check ]; then
  say "spike-cleanup: every guard holds; $TARGET can be removed"
  exit 0
fi

# 4. Removal: contents through the helper (root-owned), then the now empty directory itself.
# shellcheck disable=SC2016 # the script is expanded by the container's sh
docker run --rm --network none -v "$TARGET:/target" "$SNAPSHOT_IMAGE" \
  sh -c 'find /target -mindepth 1 -delete' remove-spike >&2 || partly "removal in the helper container failed"
rmdir "$TARGET" || partly "could not remove the emptied $TARGET"
record ok
say "spike-cleanup: $TARGET removed"
