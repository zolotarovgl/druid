"""workflow/og_origin.py: strict Dollo origin (MRCA of the member species) on a species tree."""
import ast
from pathlib import Path

import pytest

from phylocli import core  # noqa: F401  (puts workflow/ on sys.path)
import og_origin  # noqa: E402
from og_origin import Origin, OriginTree, parse_newick  # noqa: E402

V3 = (Path(__file__).parent / "data/species_tree.v3.newick").read_text()


def test_v3_tree_tips_and_unlabelled_nodes():
    t = OriginTree(V3)
    assert len(t.tips) == 59 and {"Mlei", "Hsap", "Cowc", "Mbre"} <= t.tips
    unl, stack = [], [t.root]
    while stack:
        n = stack.pop()
        stack.extend(n.children)
        if n.children and not n.name:
            unl.append(sorted(c.name or "?" for c in n.children))
    assert sorted(unl) == [["?", "Pliv"], ["Choanozoa", "Cowc"], ["Lytvar", "Spur"]]


@pytest.mark.parametrize("species, expected", [
    (["Mlei"], Origin("Mlei", 8)),                                  # one species: its tip
    (["Mlei", "Mlei"], Origin("Mlei", 8)),
    (["Mbre", "Sros"], Origin("Choanoflagellata", 2)),
    (["Hvul", "Turdoh"], Origin("Anthoathecata", 9)),               # inside a 3-way polytomy
    (["Spur", "Pliv"], Origin("~Eleutherozoa", 10)),                # unlabelled node
    (["Spur", "Lytvar"], Origin("~Eleutherozoa", 11)),              # its unlabelled child
    (["Mlei", "Cowc"], Origin("root", 0)),                          # the unlabelled root
    (["Mlei", "Hsap"], Origin("Metazoa", 2)),
    (["Bolinf", "Mlei"], Origin("Ctenophora.Mlei_Bol", 7)),         # dots in labels
    (["Mlei", "Zzz"], Origin("Mlei", 8)),                           # off-tree species ignored
])
def test_origin_on_v3(species, expected):
    assert OriginTree(V3).origin(species) == expected


def test_origin_none_when_no_species_on_the_tree():
    assert OriginTree(V3).origin(["Zzz", "Yyy"]) is None
    assert OriginTree(V3).origin([]) is None


def test_unlabelled_without_labelled_ancestor_is_tilde_root():
    t = OriginTree("((a,b),c);")
    assert t.origin(["a", "b"]) == Origin("~root", 1)
    assert t.origin(["a", "c"]) == Origin("root", 0)


def test_parse_newick_lengths_whitespace_and_errors():
    r = parse_newick(" ((A:1, B:0.5)AB:2,\n C)Top;")
    assert r.name == "Top" and [c.name for c in r.children] == ["AB", "C"]
    assert [c.name for c in r.children[0].children] == ["A", "B"]
    assert parse_newick("A;").name == "A"
    for bad in ["", "((A,B);", "(A,B));", "(A,B);(C,D);"]:
        with pytest.raises(ValueError):
            parse_newick(bad)
    with pytest.raises(ValueError):
        OriginTree("(A,(A,B));")                                    # duplicate tip


def test_deep_tree_has_no_recursion_limit():
    text = "(" * 3000 + "A" + "".join(f",B{i})" for i in range(3000)) + ";"
    assert OriginTree(text).origin(["A"]).depth == 3000


def test_og_origin_imports_only_the_standard_library():
    tree = ast.parse(Path(og_origin.__file__).read_text())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"__future__", "collections", "typing"}
