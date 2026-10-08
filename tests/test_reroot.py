"""workflow/reroot_to_generax.py: put the GeneRax root back on the GXSUP tree (Issues.md I93)."""
import pytest

ete3 = pytest.importorskip("ete3")
import reroot_to_generax as rr  # noqa: E402

# GeneRax: rooted between (a,b,c) and (d,e,f)
GX = "(((a:1,b:1)1:1,c:1)1:1,((d:1,e:1)1:1,f:1)1:1);"
# IQ-TREE -te output: same unrooted topology, drawn at leaf a, SH-aLRT supports
SUP = "(a:1,b:1,(c:1,((d:1,e:1)87:1,f:1)95:1)70:1);"


def _run(tmp_path, gx, sup):
    g, s, o = tmp_path / "gx.tree", tmp_path / "sup.tree", tmp_path / "out.tree"
    g.write_text(gx)
    s.write_text(sup)
    rr.main(str(g), str(s), str(o))
    return ete3.Tree(str(o), format=0)


def _sides(t):
    return sorted(sorted(c.get_leaf_names()) for c in t.get_children())


def test_root_restored_supports_kept(tmp_path):
    t = _run(tmp_path, GX, SUP)
    assert _sides(t) == [["a", "b", "c"], ["d", "e", "f"]]
    sup = {frozenset(n.get_leaf_names()): n.support for n in t.traverse()
           if not n.is_leaf() and not n.is_root()}
    assert sup[frozenset("de")] == 87 and sup[frozenset("ab")] == 70


def test_root_on_single_leaf(tmp_path):
    t = _run(tmp_path, "(f:1,((a:1,b:1)1:1,(c:1,(d:1,e:1)1:1)1:1)1:1);",
             "(a:1,b:1,((c:1,(d:1,e:1)87:1)95:1,f:1)70:1);")
    assert _sides(t) == [["a", "b", "c", "d", "e"], ["f"]]


def test_topology_mismatch_stops(tmp_path):
    with pytest.raises(SystemExit, match="RF"):
        _run(tmp_path, GX, "(a:1,c:1,(b:1,((d:1,e:1)87:1,f:1)95:1)70:1);")


def test_leaf_set_mismatch_stops(tmp_path):
    with pytest.raises(SystemExit, match="leaf sets"):
        _run(tmp_path, GX, "(a:1,b:1,(c:1,((d:1,g:1)87:1,f:1)95:1)70:1);")
