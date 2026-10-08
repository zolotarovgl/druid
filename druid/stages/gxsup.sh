#!/usr/bin/env bash
set -euo pipefail
export PYTHONNOUSERSITE=1
GTREE="$1"
ALN="$2"
PHYLOG="$3"

# Reuse the model PHY selected for this family; they differ per family
# (LG+I+G4, WAG+F+G4, JTT+G4, ...), so a single hard-coded model would be wrong.
MODEL=$(sed -n 's/.*Best-fit model: \([^ ]*\).*/\1/p' ${PHYLOG} | head -1)
if [[ -z "$MODEL" ]]; then MODEL="${SUBS_MODEL}+G4"; fi
echo "${ID}: fixed-topology support under $MODEL"

iqtree2 -s ${ALN} -te ${GTREE} -m "$MODEL" \
    --alrt 1000 --keep-ident -nt ${CPUS} \
    -pre ${ID}.gxsup --quiet -redo

# --alrt writes TWO values per node, "<parametric aLRT>/<SH-aLRT>"; POSSVM needs one
# float, so keep the second. (Checked against a --alrt 0 run, which emits the
# parametric value in the first field.)
sed -E 's/\)([0-9.]*)\/([0-9.]*):/)\2:/g' \
    ${ID}.gxsup.treefile > ${ID}.generax.support.tree

grep -q ';' ${ID}.generax.support.tree || { echo "empty support tree" >&2; exit 1; }

# IQ-TREE -te keeps the GeneRax topology but writes the tree UNROOTED, drawn at alignment
# sequence #1. POSSVM then runs with --skiproot, i.e. on that arbitrary root (Issues.md I93,
# 2022_Mlei). Put the GeneRax root back; the script checks RF 0, unchanged supports and the
# root split, and fails the task (no output published) if any check fails.
python ${PROJECT_DIR}/workflow/reroot_to_generax.py \
    ${GTREE} ${ID}.generax.support.tree ${ID}.generax.support.rooted.tree
mv ${ID}.generax.support.rooted.tree ${ID}.generax.support.tree
