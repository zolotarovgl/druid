import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workflow"))

from phylocli import core  # noqa: E402

HEADER = "id aln_mem aln_time gr_mem gr_time gr_watcher_mem gr_watcher_time phy_mem phy_time pvm_mem pvm_time"
ROW = "tfs.A.HG11 800.MB 45.min 3100.MB 120.min 3100.MB 180.min 800.MB 1140.min 800.MB 9.min"


def _w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.fixture
def results_tree(tmp_path):
    root = tmp_path / "v3"
    out = root / "results"
    _w(out / "clusters/tfs.A.HG1.fasta", ">a\nAA\n>b\nAA\n>c\nAA\n")
    _w(out / "clusters/tfs.A.HG11.fasta", ">a\nAA\n>b\nAA\n>c\nAA\n")
    _w(out / "clusters/tfs.B.HG2.fasta", ">a\nAA\n")
    _w(out / "clusters/tfs.C_x.HG1.fasta", "".join(f">s{i}\nAA\n" for i in range(600)))
    _w(out / "align/tfs.A.HG1.aln.fasta", ">a\nAA\n")
    _w(out / "gene_trees/tfs.A.HG1.treefile", "(a,b);\n")
    _w(out / "possvm_prev/tfs.A.HG1.treefile.ortholog_groups.csv", "x\n")
    _w(out / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv", "")
    _w(root / "resources.tsv", HEADER.replace(" ", "\t") + "\n" + ROW.replace(" ", "\t") + "\n")
    _w(root / "refnames.csv", "a,b\n")
    _w(root / "species.newick", "(a,b);\n")
    cfg_file = root / "config.yaml"
    base = yaml.safe_load((ROOT / "phylocli/config.yaml").read_text())
    base["outdir"] = str(out)
    # Never read the real project's .nextflow/ run history (slow, and not a fixture).
    base["nextflow_dir"] = str(root)
    base["params"].update(resources_tsv=str(root / "resources.tsv"),
                          REFNAMES=str(root / "refnames.csv"),
                          SPECIES_TREE=str(root / "species.newick"),
                          min_seqs=2, min_distinct=1)  # fixture HGs: 3 identical seqs
    cfg_file.write_text(yaml.safe_dump(base))
    return core.load_config(cfg_file), root
