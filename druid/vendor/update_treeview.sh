#!/usr/bin/env bash
# Refresh the vendored treeview (spec docs/superpowers/specs/2026-10-12-phylocli-treeview-design.md,
# P1).  Never edit phylocli/vendor/treeview by hand: change treeview, commit it there, run this.
#   TREEVIEW_SRC          the treeview checkout to copy from (default: the cluster repo via the mount)
#   TREEVIEW_REMOTE_REPO  where to run git: host:path (ssh; git on the sshfs mount fails with
#                         "dubious ownership") or a local path
#   VENDOR_DEST           the directory that gets treeview/ (default: next to this script)
set -euo pipefail
SRC="${TREEVIEW_SRC:-$HOME/ant/gzolotarov/projects/treeview}"
REPO="${TREEVIEW_REMOTE_REPO:-login1.hpc.crg.es:projects/treeview}"
DEST="${VENDOR_DEST:-$(cd "$(dirname "$0")" && pwd)}"

_git() {
    if [[ "$REPO" == /* ]]; then
        git -C "$REPO" "$@"
    else
        ssh -o BatchMode=yes "${REPO%%:*}" "git -C ${REPO#*:} $*"
    fi
}

dirty="$(_git status --porcelain)"
if [[ -n "$dirty" ]]; then
    echo "treeview has uncommitted changes; commit them first:" >&2
    echo "$dirty" >&2
    exit 1
fi
commit="$(_git rev-parse HEAD)"
mkdir -p "$DEST/treeview"
rsync -a --delete --exclude tests/ --exclude __pycache__/ --exclude VENDORED \
    "$SRC/treeview/" "$DEST/treeview/"
printf 'source: %s (copied from %s)\ncommit: %s\ndate: %s\n' \
    "$REPO" "$SRC" "$commit" "$(date +%d/%m/%Y)" > "$DEST/treeview/VENDORED"
echo "vendored treeview $commit into $DEST/treeview"
