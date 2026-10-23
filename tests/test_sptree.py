"""sptree: prune, add_sister, carry_to_origin, placements, build_trees; the tree blockers."""
from __future__ import annotations

from ete3 import Tree

from druid import paths, project, sptree as sp, setup_state as ss
from druid import yamledit
from tests.test_setup_state import _raw, proj  # noqa: F401  (fixture)

NW = "((A:1,B:1)AB:2,(C:1,D:1)CD:2)R;"


def _t(nw):
    return Tree(nw, format=1)


def _is_binary(nw):
    return all(len(n.children) in (0, 2) for n in _t(nw).traverse())


def test_prune_keeps_internal_names_and_lengths():
    t = _t(sp.prune(NW, {"A", "B", "C"}))
    assert {n.name for n in t.iter_leaves()} == {"A", "B", "C"}
    assert (t & "AB").dist == 2 and (t & "A").dist == 1
    assert (t & "C").dist == 3                       # D gone: C absorbs CD's length 2 + its own 1


def test_add_sister_of_tip():
    t = _t(sp.add_sister(NW, frozenset({"A"}), "X"))
    a, x = t & "A", t & "X"
    assert a.up is x.up and a.up.up.name == "AB" and a.up.name == ""
    assert a.dist == 1 and x.dist == 1 and a.up.dist == 1
    assert _is_binary(sp._dump(t))


def test_add_sister_of_internal():
    t = _t(sp.add_sister(NW, frozenset({"A", "B"}), "X"))
    ab = t & "AB"
    assert {c.name for c in ab.up.children} == {"AB", "X"}
    assert ab.up.dist == 2 and ab.dist == 1


def test_add_sister_of_root():
    t = _t(sp.add_sister(NW, frozenset("ABCD"), "X"))
    assert {c.name for c in t.children} == {"R", "X"}


def test_add_sister_rejects_unknown_tipset_and_duplicate():
    for ts, new in ((frozenset({"A", "C"}), "X"), (frozenset({"A"}), "B")):
        try:
            sp.add_sister(NW, ts, new)
        except ValueError:
            continue
        raise AssertionError("expected ValueError")


def test_carry_to_origin_exact_clade():
    t = _t(sp.carry_to_origin("((A:1,B:1)AB:2,(C:1,D:1)CD:2)R;", frozenset({"A", "B"}), "X"))
    assert {c.name for c in (t & "AB").up.children} == {"AB", "X"}


def test_carry_to_origin_inside_polytomy():
    t = _t(sp.carry_to_origin("(A:1,B:1,C:1,D:1)R;", frozenset({"A", "B"}), "X"))
    assert len(t.children) == 5 and "X" in {c.name for c in t.children}


def test_placements_roundtrip(tmp_path):
    paths.use(tmp_path)
    (tmp_path / "druid.yaml").write_text("")
    f = tmp_path / "placements.tsv"
    assert sp.read_placements(f) == []
    pl = [sp.Placement("X", frozenset({"A", "B"})), sp.Placement("Y", frozenset({"C"}))]
    sp.write_placements(f, pl)
    assert sp.read_placements(f) == pl


def test_build_trees_drops_stale_placements():
    pl = [sp.Placement("X", frozenset({"A"})), sp.Placement("Gone", frozenset({"A"})),
          sp.Placement("Y", frozenset({"Q"}))]
    b, o, notes = sp.build_trees(NW, "(A:1,B:1,C:1,D:1)R;", ["A", "B", "C", "X", "Y"], pl)
    assert sp.tips(b) == {"A", "B", "C", "X"} and sp.tips(o) == {"A", "B", "C", "X"}
    assert any("Gone" in n for n in notes) and any("Y" in n for n in notes)
    assert sp.missing(NW, ["A", "X", "Y"], pl[:1]) == ["Y"]


def test_blocker_tree_missing_and_polytomy(proj, tmp_path):  # noqa: F811
    root, prot = proj
    (prot / "Ccc_long.pep.fasta").write_text(">x\nM\n")
    raw, cfg = _raw()
    (root / "data" / "base_tree.binary.newick").write_text("(Aaa:1,Bbb:1)R;")
    (root / "data" / "base_tree.newick").write_text("(Aaa:1,Bbb:1)R;")
    assert ss.blockers({**raw, "species": ["Aaa", "Bbb"]}, cfg, root) == []
    assert ss.blockers({**raw, "species": ["Aaa", "Bbb"], "params": {**raw.get("params", {}), "origins": False}},
                       cfg, root) == []
    (root / "data" / "base_tree.binary.newick").write_text("(Aaa:1,Bbb:1,Ccc:1)R;")
    (root / "data" / "base_tree.newick").write_text("(Aaa:1,Bbb:1,Ccc:1)R;")
    (root / "data" / "my.newick").write_text("(Aaa:1,Bbb:1,Ccc:1)R;")
    p = {**raw.get("params", {}), "run_generax": True}
    out = ss.blockers({**raw, "species": ["Aaa", "Bbb", "Ccc"], "params": p,
                       "tree_source": "data/my.newick"}, cfg, root)
    assert out == ["tree_source has polytomies; GeneRax needs a binary tree"]
    (root / "data" / "my.newick").write_text("(Aaa:1,Bbb:1)R;")
    out = ss.blockers({**raw, "species": ["Aaa", "Ccc"], "params": p,
                       "tree_source": "data/my.newick"}, cfg, root)
    assert out == ["1 ticked species not on the tree: Ccc"]
