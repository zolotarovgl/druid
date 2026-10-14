#!/usr/bin/env bash
# step1.nf SEARCH, one family. Args: GENEFAM INFASTA [HMM_DIR]. Env: ID=<pref>.<family>, CPUS,
# DRUID_HOME, PROJECT_DIR, pfam_db, domain_expand.
set -euo pipefail
export PYTHONNOUSERSITE=1
GENEFAM="$1"
INFASTA="$2"
HMMDIR="${3:-}"
PREF="${ID%%.*}"
FAMILY="${ID#*.}"

# helper/hmmsearch.py fetches every model missing from --hmm_dir INTO that directory. Work on a
# copy so the configured directory is never written (step1.nf got this from stageInMode 'copy';
# phylocli symlinks its inputs and runs many families at once).
if [[ -n "${HMMDIR}" ]]; then
    rm -rf hmm_dir.work
    cp -rL "${HMMDIR}" hmm_dir.work
    HMMDIR=hmm_dir.work
fi

echo "Running hmmsearch for ${FAMILY}"

python ${DRUID_HOME}/submodules/phylogeny/main.py hmmsearch \
	-f ${INFASTA} \
	-g ${GENEFAM} \
	${FAMILY} \
	-o . \
	--pfam_db ${pfam_db} \
	${HMMDIR:+--hmm_dir ${HMMDIR}} \
	--domain_expand ${domain_expand} \
	--ncpu ${CPUS}

# main.py hmmsearch looks the family up by NAME (column 1; the last row wins) and names its
# outputs after THAT row's prefix; for a name it cannot find it logs an error and exits 0. Either
# way nothing named ${ID}.* exists here, and the touches below publish an empty "no hits" result
# (measured: rbp.CSD, whose hits were written as tfs.CSD.*). Kept as step1.nf does it (decided by
# Grygoriy 09/10/2026: warning, not failure) -- but say so.
if ! compgen -G "${ID}.*" > /dev/null; then
    other=""
    for f in *."${FAMILY}".genes.list; do
        [[ -e "$f" ]] || continue
        other+="${other:+, }${f%.genes.list}.*"
    done
    if [[ -n "$other" ]]; then
        echo "WARNING: family name ${FAMILY} is listed under more than one prefix in ${GENEFAM};" \
             "hmmsearch keys rows by name, so ${ID}'s hits are written as ${other} and ${ID}" \
             "is published empty (looks like \"no hits\")" >&2
    else
        echo "WARNING: main.py hmmsearch wrote nothing named ${ID}.* (family ${FAMILY} not found" \
             "in ${GENEFAM}?); ${ID} is published empty (looks like \"no hits\")" >&2
    fi
fi

touch ${ID}.domains.fasta
touch ${ID}.domains.csv
touch ${ID}.domains_ummerged.csv
touch ${ID}.genes.list
