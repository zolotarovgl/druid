#!/usr/bin/env bash
set -euo pipefail
export PYTHONNOUSERSITE=1
FASTA="$1"

NSEQ=$(grep -c '^>' ${FASTA} || true)
if [[ "$NSEQ" -lt 2 ]]; then
    echo "Alignment input for ${ID} contains fewer than 2 sequences; cannot build a trimmed alignment." >&2
    exit 1
fi
if ! clipkit --help >/dev/null 2>&1; then
    echo "clipkit is required for Step 2 trimming but is not runnable in the current environment." >&2
    exit 1
fi
python ${PROJECT_DIR}/phylogeny/main.py align -f ${FASTA} -o ${ID}.aln.fasta -c ${CPUS} -m "${MAFFT_OPT}"
python ${PROJECT_DIR}/workflow/remove_gaponly.py ${ID}.aln.fasta ${ID}.aln.fasta_tmp
mv ${ID}.aln.fasta_tmp ${ID}.aln.fasta
