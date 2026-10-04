#!/usr/bin/env bash
set -euo pipefail
export PYTHONNOUSERSITE=1
ALN="$1"
TREE="$2"
SPECIES_TREE_FILE="$3"

export OMP_NUM_THREADS=${CPUS}
export OPENBLAS_NUM_THREADS=${CPUS}
export MKL_NUM_THREADS=${CPUS}
export NUMEXPR_NUM_THREADS=${CPUS}

GR_STASH_DIR="${OUTDIR}/generax_ckp"
GR_STASH="$GR_STASH_DIR/${ID}.progress.tree"
mkdir -p "$GR_STASH_DIR"

touch ${ID}.progress.tree

# GeneRax has NO checkpoint of its own: a killed run loses everything and the retry
# restarts from the original IQ-TREE topology. Its SPR search improves the tree
# iteratively though, and the watcher below already snapshots that. So stash the
# snapshot somewhere stable and start the next attempt from it. Measured on the TF
# run: the giants were being killed at 16-18 h having discarded every previous hour.
#
# Validation before use: same tip count as the alignment and a trailing ';'. The
# snapshot is a plain cp of a file GeneRax may be mid-write on, so a truncated copy
# is expected occasionally and must not be fed back in.
GENE_TREE="${TREE}"
if [[ -s "$GR_STASH" ]]; then
    want=$(grep -c '^>' ${ALN})
    got=$(tr -cd ',' < "$GR_STASH" | wc -c)
    got=$(( got + 1 ))
    if [[ "$got" -eq "$want" ]] && tail -c 2 "$GR_STASH" | grep -q ';'; then
        cp "$GR_STASH" ${ID}.resume.tree
        GENE_TREE="${ID}.resume.tree"
        echo "Resuming ${ID} from stashed progress tree ($got tips)" >&2
    else
        echo "Discarding stashed progress tree for ${ID}: $got/$want tips, or no terminal ';'" >&2
    fi
fi

stash_progress() {
    if [[ -s ${ID}.progress.tree ]] && tail -c 2 ${ID}.progress.tree | grep -q ';'; then
        cp -f ${ID}.progress.tree "$GR_STASH.tmp" && mv -f "$GR_STASH.tmp" "$GR_STASH"
    fi
    return 0
}

progress_watcher() {
    while kill -0 $MAIN_PID 2>/dev/null; do
        if [[ -f ${ID}_generax/results/${ID}/geneTree.newick ]]; then
            cp ${ID}_generax/results/${ID}/geneTree.newick \
            ${ID}.progress.tree 2>/dev/null || true
        fi
        sleep 10
    done
}

python ${PROJECT_DIR}/phylogeny/main.py generax \
    --name ${ID} \
    --alignment ${ALN} \
    --gene_tree $GENE_TREE \
    --species_tree ${SPECIES_TREE_FILE} \
    --output_dir ${ID}_generax \
    --subs_model ${SUBS_MODEL} \
    --max_spr ${MAX_SPR} \
    --cpus ${CPUS} \
    --logfile ${ID}.generax.log \
    --outfile ${ID}.generax.tree &

MAIN_PID=$!

progress_watcher &
WATCH_PID=$!

cleanup() {
    kill $WATCH_PID 2>/dev/null || true
    wait $WATCH_PID 2>/dev/null || true
    stash_progress
}
trap cleanup EXIT INT TERM
trap 'cleanup; exit 140' USR2

wait $MAIN_PID
EXIT_CODE=$?

echo "GeneRax exit code: $EXIT_CODE"

if [[ -f ${ID}_generax/results/${ID}/geneTree.newick ]]; then
    cp ${ID}_generax/results/${ID}/geneTree.newick ${ID}.progress.tree || true
fi

# Keep GeneRax's reconciliation products (orthogroups, events, transfers). They are
# written whether or not we ask, and were being discarded with the work directory.
if [[ -d ${ID}_generax/reconciliations ]]; then
    cp -r ${ID}_generax/reconciliations ${ID}.reconciliations || true
fi

if [[ "$EXIT_CODE" -eq 0 ]]; then
    rm -f "$GR_STASH"
else
    stash_progress
fi

exit $EXIT_CODE
