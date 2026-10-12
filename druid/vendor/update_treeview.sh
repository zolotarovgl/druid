#!/usr/bin/env bash
# Refresh the vendored treeview (spec docs/superpowers/specs/2026-10-12-phylocli-treeview-design.md,
# P1).  Never edit phylocli/vendor/treeview by hand: change treeview, commit it there, run this.
# The bytes are extracted from the commit itself (git archive), so the `commit:` stamped in
# VENDORED always describes exactly what was copied.
#   TREEVIEW_REMOTE_REPO  the treeview repo, as host:path (git runs over ssh; git on the sshfs mount
#                         fails with "dubious ownership") or a local path
#   VENDOR_DEST           the directory that gets treeview/ (default: next to this script)
set -euo pipefail
REPO="${TREEVIEW_REMOTE_REPO:-login1.hpc.crg.es:projects/treeview}"
DEST="${VENDOR_DEST:-$(cd "$(dirname "$0")" && pwd)}"

_git() {
    if [[ "$REPO" == /* ]]; then
        git -C "$REPO" "$@"
    else
        local cmd; cmd="git -C $(printf '%q' "${REPO#*:}")"
        local a; for a in "$@"; do cmd+=" $(printf '%q' "$a")"; done
        ssh -o BatchMode=yes "${REPO%%:*}" "$cmd"
    fi
}

# Untracked files are not in the commit and cannot end up in the copy, so they do not block.
dirty="$(_git status --porcelain --untracked-files=no)"
if [[ -n "$dirty" ]]; then
    echo "treeview has uncommitted changes; commit them first:" >&2
    echo "$dirty" >&2
    exit 1
fi
commit="$(_git rev-parse HEAD)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
_git archive "$commit" treeview | tar -x -C "$tmp"
mkdir -p "$DEST/treeview"
rsync -a --delete --exclude tests/ --exclude __pycache__/ --exclude VENDORED \
    "$tmp/treeview/" "$DEST/treeview/"
printf 'source: %s\ncommit: %s\ndate: %s\n' \
    "$REPO" "$commit" "$(date +%d/%m/%Y)" > "$DEST/treeview/VENDORED"
echo "vendored treeview $commit into $DEST/treeview"
