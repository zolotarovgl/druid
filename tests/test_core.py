import dataclasses
from pathlib import Path

import pytest

import report_status
from phylocli import core


def test_expected_excludes_single_seq(results_tree):
    cfg, _ = results_tree
    assert core.expected(cfg) == {"tfs.A.HG1", "tfs.A.HG11", "tfs.C_x.HG1"}


def test_ids_file_blank_lines_and_unknown(results_tree, tmp_path):
    cfg, _ = results_tree
    f = tmp_path / "ids.txt"; f.write_text("tfs.A.HG1  \n\n tfs.NOPE.HG9\n")
    errs = core.validate(cfg, "align", core.read_ids(f), queued=set())
    assert errs["unknown"] == ["tfs.NOPE.HG9"]


def test_hg1_vs_hg11_possvm_done(results_tree):
    cfg, _ = results_tree
    d = report_status.done_by_stage(str(cfg.outdir), core.expected(cfg))
    assert d["possvm_prev"] == {"tfs.A.HG1"}          # HG11 not matched by HG1's file
    assert "tfs.A.HG11" not in d["possvm"]            # 0-byte file is not done


def test_output_exists_refused(results_tree):
    cfg, _ = results_tree
    errs = core.validate(cfg, "align", ["tfs.A.HG1", "tfs.A.HG11"], queued=set())
    assert errs["output_exists"] == ["tfs.A.HG1"]


def test_input_missing(results_tree):
    cfg, _ = results_tree
    errs = core.validate(cfg, "tree", ["tfs.A.HG11"], queued=set())
    assert errs["input_missing"] == ["tfs.A.HG11"]


def test_queued_refused(results_tree):
    cfg, _ = results_tree
    assert core.validate(cfg, "align", ["tfs.A.HG11"], queued={"tfs.A.HG11"})["queued"] == ["tfs.A.HG11"]


def test_not_applicable(results_tree):
    cfg, _ = results_tree
    cfg2 = dataclasses.replace(cfg, params={**cfg.params, "run_generax": False})
    assert core.validate(cfg2, "generax", ["tfs.A.HG11"], set())["not_applicable"] == ["tfs.A.HG11"]


@pytest.mark.parametrize("s,mb", [("800.MB",800),("2.GB",2048),("4G",4096),("500MB",500),("3100.MB",3100)])
def test_parse_mem(s, mb): assert core.parse_mem_mb(s) == mb


@pytest.mark.parametrize("s,m", [("45.min",45),("1140.min",1140),("1.h",60),("2h",120),("30m",30),("1d",1440)])
def test_parse_time(s, m): assert core.parse_time_min(s) == m


def test_resources_defaults_and_table(results_tree):
    cfg, _ = results_tree; t = core.load_resources_tsv(Path(cfg.params["resources_tsv"]))
    assert core.resources(cfg, "tree", "tfs.A.HG1", t) == core.Res(4, 300, 30, "normal", "B:USR2@180")
    assert core.resources(cfg, "tree", "tfs.A.HG11", t) == core.Res(4, 800, 1140, "normal", "B:USR2@180")
    assert core.resources(cfg, "align", "tfs.A.HG11", t).mem_mb == 4096      # floor 4 GB
    assert core.resources(cfg, "generax", "tfs.A.HG11", t).time_min == 120    # gr_time wins
    assert core.resources(cfg, "tree", "tfs.C_x.HG1", t).qos == "long"        # nseq 600 > 500


def test_align_time_ignores_aln_time(results_tree):
    cfg, _ = results_tree; t = core.load_resources_tsv(Path(cfg.params["resources_tsv"]))
    assert t["tfs.A.HG11"]["aln_time"] == "45.min"
    assert core.resources(cfg, "align", "tfs.A.HG11", t).time_min == 240


def test_group_by_resources(results_tree):
    cfg, _ = results_tree
    g = core.group(cfg, "tree", ["tfs.A.HG1", "tfs.A.HG11", "tfs.C_x.HG1"])
    assert sorted(len(v) for v in g.values()) == [1, 1, 1]


def test_missing_columns_fall_back(tmp_path):
    p = tmp_path / "r.tsv"
    p.write_text("id\tphy_mem\tphy_time\nx.HG1\t1.GB\n")
    t = core.load_resources_tsv(p)
    assert t["x.HG1"]["phy_mem"] == "1.GB" and not t["x.HG1"].get("phy_time")
    assert core.load_resources_tsv(tmp_path / "none.tsv") == {}


def test_possvm_publish_exact_names(results_tree):
    cfg, _ = results_tree
    first, marker = core.publish_patterns("possvm", "tfs.A.HG1", treefile="tfs.A.HG1.generax.support.tree")
    assert marker == "tfs.A.HG1.generax.support.tree.ortholog_groups.csv"
    assert "tfs.A.HG1.generax.support.tree.pairs_orthologs.csv" in first
