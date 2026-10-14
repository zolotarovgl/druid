#!/usr/bin/env bash
# step1.nf CLUSTER, one family. Arg: DOMAINS_FASTA. Env: ID=<pref>.<family>, CPUS, DRUID_HOME,
# PROJECT_DIR, max_n, s2_inflation, min_seqs, min_distinct.
set -euo pipefail
export PYTHONNOUSERSITE=1
DOMAINS="$1"

echo "Clustering: ${DOMAINS}"

python ${DRUID_HOME}/submodules/phylogeny/main.py cluster \
	-f ${DOMAINS} \
	--out_file ${ID}_cluster.tsv \
	-c ${CPUS} \
	-m ${max_n} \
	-i ${s2_inflation}

# (step1.nf named the loop variable ID; renamed HG here, ID is the family id)
samtools faidx ${DOMAINS}
while read -r HG; do
	[ -n "$HG" ] || continue
	xargs samtools faidx ${DOMAINS} < <(awk -v ID="$HG" '$1==ID { print $2 }' ${ID}_cluster.tsv) > ${ID}.${HG}.fasta
done < <(cut -f 1 ${ID}_cluster.tsv | sort -u)

# Guarantee structural outputs
touch ${ID}_cluster.tsv

# Small HGs are not written (spec, 08/10/2026): delete the HG FASTAs step2 would skip, by the
# rule report_status.expected_hgs uses. ${ID}_cluster.tsv stays complete (every HG and member).
python ${DRUID_HOME}/druid/helpers/drop_small_hgs.py ${ID} ${min_seqs} ${min_distinct}
