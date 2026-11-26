#!/usr/bin/env bash
# Refresh the vendored phylohpc step-2 report script.  Never edit druid/vendor/report_step2 by
# hand: change it in phylohpc, commit it there, run this.  The bytes are extracted from the commit
# itself (git archive), so the `commit:` stamped in VENDORED describes exactly what was copied.
#   REPORT_REMOTE_REPO  the phylohpc repo, as host:path (git over ssh) or a local path
#   VENDOR_DEST         the directory that gets report_step2/ (default: next to this script)
set -euo pipefail
REPO="${REPORT_REMOTE_REPO:-$HOME/Documents/projects/phylogenies/phylohpc}"
DEST="${VENDOR_DEST:-$(cd "$(dirname "$0")" && pwd)}"
FILE=workflow/report_step2.py

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
    echo "phylohpc has uncommitted changes; commit them first:" >&2
    echo "$dirty" >&2
    exit 1
fi
commit="$(_git rev-parse HEAD)"
mkdir -p "$DEST/report_step2"
_git show "$commit:$FILE" > "$DEST/report_step2/report_step2.py.new"
mv "$DEST/report_step2/report_step2.py.new" "$DEST/report_step2/report_step2.py"
printf 'source: %s\ncommit: %s\ndate: %s\n' \
    "$REPO" "$commit" "$(date +%d/%m/%Y)" > "$DEST/report_step2/VENDORED"
echo "vendored report_step2.py $commit into $DEST/report_step2"
