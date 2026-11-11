"""druid/counts.py: column data of the Counts heatmap."""
from __future__ import annotations

import types

import pytest

from druid import counts, model
from druid.counts import Col
from tests.test_model import POSSVM_HG1, og_csv


def _cfg(tmp_path):
    for d in ("search", "clusters", "possvm"):
        (tmp_path / d).mkdir(exist_ok=True)
    return types.SimpleNamespace(outdir=tmp_path)


def test_family_cols_counts_species_and_skips(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "search/tfs.A.genes.list").write_text("Mlei_g1\nMlei_g2\n\n# c\nHsap_x\n")
    (tmp_path / "search/tfs.B.genes.list").write_text("")
    cols, bad = counts.family_cols(cfg, ["tfs.A", "tfs.B", "tfs.C"])
    assert cols == [Col("tfs.A", "tfs.A", {"Mlei": 2, "Hsap": 1})]
    assert bad == 1


def test_hg_cols_reads_fasta_headers(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "clusters/tfs.A.HG1.fasta").write_text(">Mlei_a x\nAC\n>Mlei_b\nAC\n>Bova_c\nAC\n")
    (tmp_path / "clusters/tfs.A.HG2.fasta").write_text(">Hsap_z\nAC\n")
    cols, bad = counts.hg_cols(cfg, ["tfs.A.HG1"])
    assert cols == [Col("tfs.A.HG1", "tfs.A.HG1", {"Mlei": 2, "Bova": 1})]
    assert bad == 0


def test_class_cols_sums_families():
    fams = [Col("tfs.A", "tfs.A", {"Mlei": 2}), Col("tfs.B", "tfs.B", {"Mlei": 1, "Hsap": 1}),
            Col("slc.X", "slc.X", {"Hsap": 4})]
    cc = counts.class_cols(fams)
    assert [(c.id, c.label, c.counts) for c in cc] == [
        ("tfs", "tfs", {"Mlei": 3, "Hsap": 1}), ("slc", "slc", {"Hsap": 4})]


def test_og_cols_labels_and_totals(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "possvm/tfs.A.HG1.generax.support.tree.ortholog_groups.csv").write_text(og_csv(POSSVM_HG1))
    ogs = model.read_ogs(cfg, "tfs.A.HG1", "possvm")
    cols = counts.og_cols(model.HGOgs("tfs.A.HG1", ogs))
    assert [c.label for c in cols] == ["HG1.0:T/Tbx19", "HG1.1:like:Eomes/Tbr1"]
    assert [c.total for c in cols] == [3, 2]
    assert cols[0].counts == {"Mlei": 2, "Hsap": 1}
    assert counts.og_cols(model.HGOgs("tfs.A.HG1", [], error="boom")) == []


def test_order_cols_default_and_by_species():
    a = Col("a", "a", {"Mlei": 1, "Hsap": 1})
    b = Col("b", "b", {"Mlei": 3})
    c = Col("c", "c", {"Hsap": 2})
    d = Col("d", "d", {"Nvec": 2})
    assert [x.id for x in counts.order_cols([a, b, c, d])] == ["b", "a", "c", "d"]
    assert [x.id for x in counts.order_cols([a, b, c, d], by={"Hsap"})] == ["c", "a", "b", "d"]


def test_zscores():
    z = counts.zscores([[1], [3]])
    assert z[0][0] == pytest.approx(-0.70710678)
    assert z[1][0] == pytest.approx(0.70710678)
    assert counts.zscores([[2, 1], [2, 3]])[0][0] == 0.0
    assert counts.zscores([[5]]) == [[0.0]]


def test_cell_colour_ends_and_luminance():
    bg, fg = counts.cell_colour(0, 2.0, "z", 2.0, 10)
    assert bg == "#b2182b" and fg == "#eeeeee"
    bg, fg = counts.cell_colour(0, 0.0, "z", 2.0, 10)
    assert bg == "#f7f7f7" and fg == "#222222"
    bg, fg = counts.cell_colour(10, 0.0, "abs", 2.0, 10)
    assert bg == "#08306b" and fg == "#eeeeee"
    bg, fg = counts.cell_colour(0, 0.0, "abs", 2.0, 10)
    assert bg == "#f7fbff" and fg == "#222222"


def test_fmt_count():
    assert [counts.fmt_count(v) for v in (0, 7, 99, 100)] == ["·", "7", "99", "99+"]
