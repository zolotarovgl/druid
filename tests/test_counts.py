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
    (tmp_path / "search/tfs.D.genes.list").mkdir()          # exists, cannot be read as a file
    cols, bad = counts.family_cols(cfg, ["tfs.A", "tfs.B", "tfs.C", "tfs.D"])
    assert cols == [Col("tfs.A", "tfs.A", {"Mlei": 2, "Hsap": 1})]
    assert bad == 1                     # tfs.D only: an absent list (tfs.C) is "not searched yet"
    assert counts.family_cols(cfg, ["tfs.C"]) == ([], 0)


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


# ---- species axis
from treeview import layout as _layout          # noqa: E402
from tests.test_model import SP4                 # noqa: E402


def _sp_model():
    from treeview import model as tvm
    return tvm.TreeModel(tvm.load(SP4), sep="_")


def test_axis_rows_in_tree_order():
    m = _sp_model()
    ax = counts.axis(m)
    want = [m.name[i] for i in _layout.clado_order(m) if m.shown_as_leaf(i)]
    assert ax.labels == want and sorted(want) == ["Bova", "Hsap", "Mlei", "Nvec"]
    assert len(ax.clado) == 4


def test_axis_clado_has_no_tip_names_and_is_capped():
    import os
    from treeview import model as tvm
    for m in (_sp_model(), tvm.TreeModel(tvm.load(os.path.join(os.path.dirname(__file__),
                                                             "data/species_tree.v3.newick")),
                                         sep="_")):
        ax = counts.axis(m)
        for clado, lab in zip(ax.clado, ax.labels):
            assert lab not in clado.plain and clado.plain.strip()
            assert clado.cell_len <= counts.CLADO_WIDTH
            assert (clado.plain + " " + lab).count(lab) == 1   # the name appears once per row


def test_collapse_sums_clade():
    m = _sp_model()
    cols = [Col("c", "c", {"Mlei": 2, "Bova": 1, "Hsap": 4})]
    assert counts.collapse_up(m, m.tip("Mlei")) is None
    ax = counts.axis(m)
    assert len(ax.leaves) == 3 and len(ax.clado) == 3
    k = next(i for i, t in enumerate(ax.tips) if "Mlei" in t)
    assert ax.tips[k] == frozenset({"Mlei", "Bova"}) and "(2 spp.)" in ax.labels[k]
    assert counts.grid(cols, ax).rows[k] == [3]
    assert counts.collapse_up(m, ax.leaves[k]) == "whole tree"
    assert len(counts.axis(m).leaves) == 3


def test_grid_off_tree_and_sums():
    ax = counts.axis(_sp_model())
    g = counts.grid([Col("c", "c", {"Mlei": 2, "Zzz": 3})], ax)
    assert g.off_tree == [3] and g.off_codes == {"Zzz": 3} and g.sums == [5]
    assert g.rows[ax.labels.index("Mlei")] == [2] and g.row_totals[ax.labels.index("Mlei")] == 2


def test_load_species_model_errors(tmp_path):
    ns = types.SimpleNamespace
    with pytest.raises((OSError, ValueError), match="SPECIES_TREE"):
        counts.load_species_model(ns(params={}))
    with pytest.raises(OSError, match="species tree"):
        counts.load_species_model(ns(params={"SPECIES_TREE": str(tmp_path / "no.nwk")}))
    bad = tmp_path / "bad.nwk"
    bad.write_text("(((")
    with pytest.raises(ValueError, match="parse"):
        counts.load_species_model(ns(params={"SPECIES_TREE": str(bad)}))
    ok = tmp_path / "ok.nwk"
    ok.write_text(SP4)
    assert counts.load_species_model(ns(params={"SPECIES_TREE": str(ok)})).ntips[0] == 4
