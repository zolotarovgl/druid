#!/usr/bin/env bash
set -euo pipefail
export PYTHONNOUSERSITE=1
TREE="$1"
REFNAMES_FILE="$2"

# --skiproot: this leg reads a GeneRax tree, which the reconciliation ALREADY rooted.
# POSSVM roots by default (iterative midpoint), and re-rooting a reconciled tree
# collapsed 38 of 146 TF families to one orthogroup spanning the whole tree
# (tfs.Forkhead.HG2: 1 group rooted vs 12 with the flag). PVM_PREV deliberately does
# NOT get this -- its IQ-TREE trees are genuinely unrooted and need the rooting.
python ${PROJECT_DIR}/phylogeny/main.py possvm \
    -t ${TREE} \
    --refsps ${REFSPECIES} \
    --skiproot \
    -r ${REFNAMES_FILE} \
    -o ${ID}.

# POSSVM reports a PLACEHOLDER as if it were support: a singleton group has no ancestor
# to test and a root-spanning group gets the root's own default, and ete3 returns 1.0 for
# both. Measured over 400 families: 15.4 % singleton, 4.8 % root-MRCA, and 19 groups whose
# 1.0 is REAL -- which is why this recomputes the MRCA instead of matching on "1.0".
# Drops singleton rows; sets support to -1 where the MRCA is the root.
for f in ${ID}.*.ortholog_groups.csv; do
    if [ -s "$f" ]; then python ${PROJECT_DIR}/workflow/possvm_postprocess.py "$f"; fi
done
