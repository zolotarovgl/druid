#!/usr/bin/env python3
"""Put the GeneRax root back on the GXSUP support tree (Issues.md I93).

`iqtree2 -te <generax.tree>` keeps the GeneRax topology but writes it UNROOTED, drawn at the first
alignment sequence. This re-roots the support tree on the GeneRax root bipartition and checks:
  1. unrooted RF(generax, support) == 0         (same topology, else stop: nothing to transfer)
  2. every bipartition keeps its support value  (re-rooting must not move supports between splits)
  3. the output root split == the GeneRax root split
usage: reroot_to_generax.py <generax.tree> <support.tree> <out.tree>
"""
import sys
import ete3


def splits(t, leaves):
    """bipartition (smaller side, ties broken by sorted name) -> support, internal non-root nodes.
    Trivial splits (one leaf) are skipped: rooting on a single leaf makes its sibling clade an
    internal node whose split is that leaf, a split with no support to carry."""
    out = {}
    for n in t.traverse():
        if n.is_leaf() or n.is_root():
            continue
        s = frozenset(n.get_leaf_names())
        k = min(s, leaves - s, key=lambda x: (len(x), sorted(x)))
        if len(k) > 1:
            out.setdefault(k, n.support)
    return out


def root_side(t, leaves):
    s = frozenset(t.get_children()[0].get_leaf_names())
    return min(s, leaves - s, key=lambda x: (len(x), sorted(x)))


def main(gx_f, sup_f, out_f):
    g, s = ete3.Tree(gx_f, format=0), ete3.Tree(sup_f, format=0)
    leaves = frozenset(g.get_leaf_names())
    if frozenset(s.get_leaf_names()) != leaves:
        sys.exit(f"ERROR {sup_f}: leaf sets differ from {gx_f}")
    if len(g.get_children()) != 2:
        sys.exit(f"ERROR {gx_f}: GeneRax tree is not bifurcating at the root")
    rf = g.robinson_foulds(s, unrooted_trees=True)[0]
    if rf != 0:
        sys.exit(f"ERROR {sup_f}: unrooted RF vs GeneRax = {rf}, topology differs")

    before = splits(s, leaves)
    side = root_side(g, leaves)
    if len(side) == 1:
        s.set_outgroup(s & next(iter(side)))
    else:
        # MRCA of `side` is only that clade once the current root lies outside it
        s.set_outgroup(s & next(iter(leaves - side)))
        s.set_outgroup(s.get_common_ancestor(list(side)))

    if root_side(s, leaves) != side:
        sys.exit(f"ERROR {sup_f}: root split after re-rooting does not match GeneRax")
    after = splits(s, leaves)
    moved = [k for k in before if k in after and before[k] != after[k]]
    if set(before) != set(after) or moved:
        sys.exit(f"ERROR {sup_f}: {len(moved)} bipartitions changed support on re-rooting")
    s.write(outfile=out_f, format=0)
    print(f"rerooted {sup_f}: root {[len(c) for c in s.get_children()]} (GeneRax "
          f"{[len(c) for c in g.get_children()]}), {len(after)} splits, supports preserved")


if __name__ == "__main__":
    main(*sys.argv[1:4])
