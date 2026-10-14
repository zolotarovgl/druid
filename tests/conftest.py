import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "druid" / "helpers"))

from druid import core, paths  # noqa: E402

HEADER = "id aln_mem aln_time gr_mem gr_time gr_watcher_mem gr_watcher_time phy_mem phy_time pvm_mem pvm_time"
ROW = "tfs.A.HG11 800.MB 45.min 3100.MB 120.min 3100.MB 180.min 800.MB 1140.min 800.MB 9.min"
GENEFAM = ("A\tPF_A\t1.1\t3\tGA\tTF\ttfs\n"
           "B\tPF_B\t1.1\t3\tGA\tTF\ttfs\n"
           "\n"
           "C_x\tPF_C\t1.1\t3\tGA\tTF\ttfs\n"
           "NEW\tPF_N\t1.1\t3\tGA\tslc\tslc\n"
           "Trail\tPF_T\t1.1\t3\tGA\tcalcium\tcal\t\n")    # trailing tab, like Carb_anhydrase / Slc26


def _w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.fixture(autouse=True)
def _no_ambient_project(monkeypatch):
    """No test sees a project it did not set up: druid.yaml discovery, DRUID_* env, --project."""
    for k in ("DRUID_PROJECT", "DRUID_CONFIG"):
        monkeypatch.delenv(k, raising=False)
    paths.use(None)
    yield
    paths.use(None)


@pytest.fixture
def results_tree(tmp_path, monkeypatch):
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
    _w(root / "origin.newick", "((Mlei:1,Bova:1)Cteno:1,(Hsap:1,Nvec:1)Para:1);\n")
    _w(root / "gene_families_searchinfo.csv", GENEFAM)
    _w(root / "input.fasta", ">p1\nMKV\n")
    _w(root / "Pfam-A.hmm", "HMMER3/f\n")
    cfg_file = root / "druid.yaml"
    base = yaml.safe_load((ROOT / "druid/templates/druid.yaml").read_text())
    base["outdir"] = str(out)
    base["runs_dir"] = "runs"
    # Never read the real project's .nextflow/ run history (slow, and not a fixture).
    base["nextflow_dir"] = str(root)
    base["params"].update(resources_tsv=str(root / "resources.tsv"),
                          REFNAMES=str(root / "refnames.csv"),
                          SPECIES_TREE=str(root / "species.newick"),
                          ORIGIN_TREE=str(root / "origin.newick"),
                          genefam_info=str(root / "gene_families_searchinfo.csv"),
                          infasta=str(root / "input.fasta"),
                          pfam_db=str(root / "Pfam-A.hmm"),
                          min_seqs=2, min_distinct=1)  # fixture HGs: 3 identical seqs
    cfg_file.write_text(yaml.safe_dump(base))
    monkeypatch.setenv("DRUID_PROJECT", str(root))
    return core.load_config(cfg_file), root
