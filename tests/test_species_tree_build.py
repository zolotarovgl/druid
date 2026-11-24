"""tools/build_species_tree.py: the consensus species tree (latest + v3 ctenophores + chromo94 + planarians)."""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from ete3 import Tree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from build_species_tree import build, clades  # noqa: E402
from druid.sptree import has_polytomy, tip_list, tips  # noqa: E402

INPUTS = ROOT / "tools" / "species_tree" / "inputs"
LATEST = (INPUTS / "latest_20251014.newick").read_text()
V3 = (INPUTS / "v3_origin.newick").read_text()
CHROMO = (ROOT / "druid" / "data" / "species_tree.chromo94.newick").read_text()


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def tips_under(newick, a, b):
    t = Tree(newick, format=1)
    return {n.name for n in t.get_common_ancestor(a, b).iter_leaves()}


def mrca_name(newick, *tp):
    return Tree(newick, format=1).get_common_ancestor(*tp).name


def test_inputs_md5():
    assert md5(INPUTS / "latest_20251014.newick") == "205631b2efb8f8e17a3a94cf858fae70"
    assert md5(INPUTS / "v3_origin.newick") == "95521216cef1137d35a9e95f515033c3"
    assert md5(ROOT / "druid" / "data" / "species_tree.chromo94.newick") == "5a8e45f5fc151b31897b525c3ba74a4c"


def test_input_facts():
    assert len(tips(LATEST)) == 178 and len(tips(V3)) == 59 and len(tips(CHROMO)) == 94
    assert mrca_name(LATEST, "Smed", "Dugjap") == "Tricladida"
    assert len(tips(V3) - tips(LATEST)) == 6 and len(tips(CHROMO) - tips(LATEST)) == 20


def test_tips_and_binary():
    o, b, _ = build(LATEST, V3, CHROMO)
    to, tb = tip_list(o), tip_list(b)
    assert len(to) == 205 == len(set(to)) and set(to) == set(tb)
    assert has_polytomy(o) and not has_polytomy(b)


def test_branch_lengths():
    o, b, _ = build(LATEST, V3, CHROMO)
    t = Tree(o, format=1)
    assert t.dist == 0 and all(n.dist == 1 for n in t.traverse() if not n.is_root())
    zero = [n for n in Tree(b, format=1).traverse() if not n.is_root() and n.dist == 0]
    assert zero and all(n.dist in (0, 1) for n in Tree(b, format=1).traverse() if not n.is_root())


def test_v3_topology_kept():
    o, _, _ = build(LATEST, V3, CHROMO)
    assert clades(o, tips(V3)) == clades(V3, tips(V3))


def test_latest_kept_outside_ctenophores():
    o, _, _ = build(LATEST, V3, CHROMO)
    L = tips(LATEST)
    cten = tips_under(LATEST, "Eupdun", "Mlei")
    assert len(cten) == 16
    strip = lambda cs: {c for c in cs if not c < cten and not c <= {"Smed", "Dugjap"}}
    assert strip(clades(o, L)) == strip(clades(LATEST, L))


def test_no_conflict_with_chromo94_outside_ctenophores():
    o, _, _ = build(LATEST, V3, CHROMO)
    C = tips(CHROMO)
    cten = tips_under(CHROMO, "Mlei", "Vmul")
    mine, theirs = clades(o, C), clades(CHROMO, C)
    for c in mine:
        if c < cten:
            continue
        for d in theirs:
            assert c <= d or d <= c or not (c & d), (sorted(c), sorted(d))


def test_ctenophores_follow_whelan():
    o, _, _ = build(LATEST, V3, CHROMO)
    c = clades(o, tips(o))
    assert frozenset({"Drygla", "Beraby", "Berfor", "Berova"}) in c
    assert frozenset({"Drygla", "Beraby", "Berfor", "Berova", "Bolinf", "Bolmic", "Mlei"}) in c


def test_planarian_clade():
    o, _, _ = build(LATEST, V3, CHROMO)
    c = clades(o, tips(o))
    for s in ({"Smed", "Spol"}, {"Djap", "Dugjap"}, {"Smed", "Spol", "Djap", "Dugjap"},
              {"Smed", "Spol", "Djap", "Dugjap", "Gtig"}, {"Smed", "Spol", "Djap", "Dugjap", "Gtig", "Pnig"}):
        assert frozenset(s) in c
    assert mrca_name(o, "Smed", "Pnig") == "Tricladida"


def test_names():
    o, _, _ = build(LATEST, V3, CHROMO)
    assert mrca_name(o, "Hsap", "Mmus") == "Euarchontoglires"
    assert mrca_name(o, "Drygla", "Beraby") == "Beroida_Dryodora"
    names = [n.name for n in Tree(o, format=1).traverse() if not n.is_leaf() and n.name]
    assert len(names) == len(set(names))


def test_cannot_place_raises():
    with pytest.raises(ValueError, match="cannot place"):
        build(LATEST, V3, "(Xnew1,Xnew2);")


def test_bad_tricladida_raises():
    bad = LATEST.replace("Dugjap", "Dugx", 1)
    with pytest.raises(ValueError):
        build(bad, V3, CHROMO)


def test_ctenophore_mismatch_raises():
    with pytest.raises(ValueError, match="Lampan.*Lampx|Lampx.*Lampan"):
        build(LATEST, V3.replace("Lampan", "Lampx"), CHROMO)


def test_species_report_lists_duplicates():
    _, _, rep = build(LATEST, V3, CHROMO)
    txt = "\n".join(rep)
    assert "Djap" in txt and "Dugjap" in txt and "Bflo" in txt and "Bflz" in txt
    for code in ("Avas", "Braflo", "Clad", "Halduj"):
        assert code in txt


def test_cli_check(tmp_path):
    script = str(ROOT / "tools" / "build_species_tree.py")
    r = subprocess.run([sys.executable, script, "--out-dir", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "species_tree.newick").is_file() and (tmp_path / "species_tree.binary.newick").is_file()
    ok = subprocess.run([sys.executable, script, "--check", str(tmp_path)], capture_output=True, text=True)
    assert ok.returncode == 0
    (tmp_path / "species_tree.newick").write_text("(A,B);")
    bad = subprocess.run([sys.executable, script, "--check", str(tmp_path)], capture_output=True, text=True)
    assert bad.returncode == 1
