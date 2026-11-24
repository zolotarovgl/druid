"""tools/build_species_tree.py: the consensus species tree (latest + v3 ctenophores + chromo94 + planarians)."""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from ete3 import Tree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from build_species_tree import _add_missing, build, clades, species_report  # noqa: E402
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


def _all_clades(newick):
    return {frozenset(x.name for x in n.iter_leaves()) for n in Tree(newick, format=1).traverse()
            if not n.is_leaf()}


def test_no_one_child_nodes():
    # final review #2: latest's 5 one-child nodes made GeneRax fail ("Cannot parse species tree")
    o, b, rep = build(LATEST, V3, CHROMO)
    assert all(len(n.children) == 2 for n in Tree(b, format=1).traverse() if not n.is_leaf())
    assert all(len(n.children) >= 2 for n in Tree(o, format=1).traverse() if not n.is_leaf())
    assert "one-child nodes collapsed: 5" in rep


def test_graft_joins_the_highest_node_with_the_same_source_tips():
    # final review #4: B is backbone-only, so the source's (A,X) says nothing about B: (A,B,X)
    out, notes = _add_missing("((A:1,B:1):1,C:1);", "((A,X),C);", "src")
    c = _all_clades(out)
    assert frozenset("ABX") in c and frozenset("AX") not in c and frozenset("AB") not in c
    assert any(n.startswith("polytomy graft: X ") for n in notes)


def test_graft_exact_source_clade_stays_a_clade():
    out, notes = _add_missing("((A:1,B:1):1,C:1);", "(((A,B),X),C);", "src")
    c = _all_clades(out)
    assert frozenset("AB") in c and frozenset("ABX") in c and frozenset("ABCX") in c
    assert not notes


def test_graft_conflict_with_the_backbone_is_reported():
    # final review #7: the source has X sister of (A,B); the backbone puts C (a source tip) inside
    out, notes = _add_missing("((A:1,C:1):1,B:1);", "(((A,B),X),C);", "src")
    assert frozenset("AC") in _all_clades(out)                   # the backbone wins
    assert [n for n in notes if n.startswith("conflict: X ")] and "C" in notes[0] and "src" in notes[0]


def test_sponge_grafts_make_no_unsupported_split():
    # final review #4: the 7 measured cases (sister in the source; the backbone relative it lacks)
    o, _, rep = build(LATEST, V3, CHROMO)
    c = clades(o, tips(o))
    for new, sis, other in (("Cliori", "Tetwil", "Stycar"), ("Halpan", "Tetwil", "Stycar"),
                            ("Theswi", "Tetwil", "Stycar"), ("Xesmut", "Aque", "Halamb"),
                            ("Dysava", "Choren", "Plespi"), ("Corcan", "Ocar", "Plajan"),
                            ("Aphvas", "Oopmin", "Avas"), ("Aphrbe", "Oopmin", "Avas")):
        assert all(other in x for x in c if {new, sis} <= x), (new, sis, other)
    # chromo94 ((Aphvas,Aphrbe),Oopmin); latest ((Avas,Oopmin),Clad), Avas and Clad not in chromo94:
    # ((Avas,Oopmin),Clad,(Aphvas,Aphrbe)), each input's clades kept, nothing more
    assert {frozenset({"Aphvas", "Aphrbe"}), frozenset({"Avas", "Oopmin"}),
            frozenset({"Avas", "Oopmin", "Clad", "Aphvas", "Aphrbe"})} <= c
    assert frozenset({"Oopmin", "Aphvas", "Aphrbe"}) not in c
    assert {"Cliori", "Xesmut", "Dysava", "Corcan", "Aphvas"} <= {x.split()[2] for x in rep
                                                                if x.startswith("polytomy graft: ")}


def test_report_lists_names_not_placed():
    o, _, rep = build(LATEST, V3, CHROMO)
    have = {n.name for n in Tree(o, format=1).traverse() if not n.is_leaf() and n.name}
    assert "name not placed: Crinoidea (latest, one-tip clade)" in rep
    for label, src in (("latest", LATEST), ("v3", V3), ("chromo94", CHROMO)):
        for n in Tree(src, format=1).traverse():
            if not n.is_leaf() and n.name and n.name not in have:
                assert [x for x in rep if x.startswith(f"name not placed: {n.name} ({label}, ")], n.name
    for x in rep:
        if x.startswith("name not placed: "):
            assert x.split()[3] not in have, x


def test_species_report_compares_sp_names_in_full(tmp_path):
    # final review #8: "Hoilungia sp. H4" / "Hoilungia sp. H11" are two species
    tax = tmp_path / "tax.tsv"
    tax.write_text("HoiH04\tHoilungia sp. H4\nHoiH11\tHoilungia sp. H11\nBflo\tBranchiostoma floridae, S238N-H82\n"
                   "Bflz\tBranchiostoma floridae, bjbf\nXa\tGenus sp A\nXb\tGenus sp. A\n")
    rep = species_report(["HoiH04", "HoiH11", "Bflo", "Bflz", "Xa", "Xb"], tax, {})
    assert not [x for x in rep if "HoiH" in x]
    assert [x for x in rep if "Bflo" in x and "Bflz" in x] and [x for x in rep if "Xa" in x and "Xb" in x]
    _, _, real = build(LATEST, V3, CHROMO)
    assert not [x for x in real if "HoiH" in x]


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


def test_shipped_matches_rebuild():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_species_tree.py"), "--check",
                        str(ROOT / "druid" / "data")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
