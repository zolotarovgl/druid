#!/usr/bin/env bash
set -euo pipefail
export PYTHONNOUSERSITE=1
ALN="$1"

CKP_DIR="${OUTDIR}/phy_ckp"
CKP_STASH="$CKP_DIR/${ID}.ckp.gz"
mkdir -p "$CKP_DIR"

# A task that times out or OOMs never reaches publishDir, so its IQ-TREE2
# checkpoint dies with the work directory and the next attempt redoes
# ModelFinder from scratch. Keep it in a stable per-family location instead,
# so retries resume where the previous attempt was killed. This is what the
# giant TF families needed: exit 140 (128+SIGUSR2) on a 24 h limit currently
# throws away every hour of work done so far.
for src in "$CKP_STASH" "${OUTDIR}/gene_trees/${ID}.ckp.gz"; do
    if [[ -s "$src" ]] && gzip -t "$src" 2>/dev/null; then
        cp "$src" ${ID}.ckp.gz
        echo "Resuming ${ID} from checkpoint $src" >> ${ID}.log
        break
    fi
done

# gzip -t before installing: SLURM's warning signal can arrive while IQ-TREE2
# is mid-write, and a truncated checkpoint makes the next attempt fail instantly
# rather than resume. A bad copy is discarded and the previous good stash kept.
stash_ckp() {
    if [[ -s ${ID}.ckp.gz ]] && gzip -t ${ID}.ckp.gz 2>/dev/null; then
        cp -f ${ID}.ckp.gz "$CKP_STASH.tmp" && mv -f "$CKP_STASH.tmp" "$CKP_STASH"
    fi
    return 0
}
trap stash_ckp EXIT
trap 'stash_ckp; exit 140' USR2
trap 'stash_ckp; exit 143' TERM

# Background + wait so the shell can service USR2 promptly; a foreground child
# would defer the trap until after it exits.
set +e
python ${DRUID_HOME}/submodules/phylogeny/main.py phylogeny -f ${ALN} --outprefix ${ID} -c ${CPUS} --method ${TREE_METHOD} --iqtree2_model ${IQTREE2_MODEL} >> ${ID}.log 2>&1 &
PY_PID=$!
wait "$PY_PID"
RC=$?
set -e

trap - EXIT USR2 TERM
if [[ "$RC" -eq 0 ]]; then
    # Succeeded: drop the stash so a later rerun on changed input can never
    # resume from a stale checkpoint.
    rm -f "$CKP_STASH"
else
    stash_ckp
fi
exit $RC
