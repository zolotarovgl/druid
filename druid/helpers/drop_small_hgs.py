#!/usr/bin/env python3
"""Delete the <ID>.HG*.fasta files in the current directory that step2 would skip.

Called by phylocli/stages/cluster.sh after the HG FASTAs are written and BEFORE anything is
published (phylocli and step1.nf CLUSTER alike): an HG is kept only with >= MIN_SEQS sequences
and >= MIN_DISTINCT distinct ones -- report_status.passes, the rule expected_hgs applies -- so
step1 and step2 can never disagree. <ID>_cluster.tsv is not touched: it stays the complete MCL
membership record, and HG numbering keeps its gaps.

Usage:  drop_small_hgs.py ID MIN_SEQS MIN_DISTINCT
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_status  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        sys.exit(__doc__.strip().splitlines()[-1])
    fam, min_seqs, min_distinct = argv[1], int(argv[2]), int(argv[3])
    files = sorted(glob.glob(glob.escape(fam) + ".HG*.fasta"))
    small = [f for f in files if not report_status.passes(f, min_seqs, min_distinct)]
    for f in small:
        os.remove(f)
    print(f"{fam}: skipped {len(small)} HGs below min_seqs/min_distinct "
          f"({min_seqs}/{min_distinct}); kept {len(files) - len(small)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
