"""Species-tree operations (sub-project 2): prune to the ticked species, add a species as the sister
of a node, carry that placement to the polytomous origin tree, the placements file. Pure: plain
str / set / frozenset / list arguments, no setup_state or model; the only write is the placements
file, through paths. Newicks are ete3 format=1 (named internal nodes, branch lengths)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from ete3 import Tree

from druid import paths

PLACEMENTS = "placements.tsv"       # under data/: `sp<TAB>tip1,tip2,...` (the sister node's tips)


def _load(newick: str) -> Tree:
    return Tree(newick, format=1)


def _dump(t: Tree) -> str:
    return t.write(format=1, format_root_node=True)


def tips(newick: str) -> set:
    if not newick.strip():
        return set()
    return {n.name for n in _load(newick).iter_leaves()}


def tip_list(newick: str) -> list:
    """The tip names in tree order (tips() as a list)."""
    if not newick.strip():
        return []
    return [n.name for n in _load(newick).iter_leaves()]


def has_polytomy(newick: str) -> bool:
    return bool(newick.strip()) and any(len(n.children) > 2 for n in _load(newick).traverse())


def prune(newick: str, keep: set) -> str:
    """Drop the tips not in `keep`; internal names and branch lengths survive. "" if none remain."""
    t = _load(newick)
    kept = [n for n in t.iter_leaves() if n.name in keep]
    if not kept:
        return ""                                   # nothing of the tree is ticked
    t.prune(kept, preserve_branch_length=True)
    return _dump(t)


def _find(t: Tree, tipset: frozenset):
    for n in t.traverse():
        if {x.name for x in n.iter_leaves()} == set(tipset):
            return n
    return None


def _graft(t: Tree, node, new: str) -> Tree:
    """New unnamed parent over (node, new); it takes node's length, node and new get 1."""
    length = node.dist
    parent = node.up
    leaf = Tree()
    leaf.name, leaf.dist = new, 1
    if parent is None:
        root = Tree()
        root.dist = 0
        node.dist = 1
        root.add_child(node)
        root.add_child(leaf)
        return root
    node.detach()
    mid = parent.add_child(dist=length)
    node.dist = 1
    mid.add_child(node)
    mid.add_child(leaf)
    return t


def add_sister(newick: str, tipset: frozenset, new: str) -> str:
    t = _load(newick)
    if new in {n.name for n in t.iter_leaves()}:
        raise ValueError(f"{new} is already on the tree")
    node = _find(t, frozenset(tipset))
    if node is None:
        raise ValueError(f"no node with exactly the tips {sorted(tipset)}")
    return _dump(_graft(t, node, new))


def carry_to_origin(newick: str, tipset: frozenset, new: str) -> str:
    """Exact clade: as add_sister. Otherwise `new` joins the smallest node whose tips contain
    `tipset` as one more child (the polytomy it sits in)."""
    t = _load(newick)
    if new in {n.name for n in t.iter_leaves()}:
        raise ValueError(f"{new} is already on the tree")
    ts = set(tipset)
    node = _find(t, frozenset(ts))
    if node is not None:
        return _dump(_graft(t, node, new))
    cands = [n for n in t.traverse() if ts <= {x.name for x in n.iter_leaves()}]
    if not cands:
        raise ValueError(f"no node contains the tips {sorted(tipset)}")
    host = min(cands, key=lambda n: len(n.get_leaves()))
    host.add_child(name=new, dist=1)
    return _dump(t)


@dataclass(frozen=True)
class Placement:
    sp: str
    tipset: frozenset


def read_placements(path) -> List[Placement]:
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text().splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 2 or not parts[0].strip():
            continue
        out.append(Placement(parts[0].strip(),
                             frozenset(x.strip() for x in parts[1].split(",") if x.strip())))
    return out


def write_placements(path, pl: List[Placement]) -> Path:
    text = "".join(f"{x.sp}\t{','.join(sorted(x.tipset))}\n" for x in pl)
    return paths.write_text(path, text)


def build_trees(base_binary: str, base_origin: str, species: List[str],
                pl: List[Placement]) -> Tuple[str, str, List[str]]:
    keep = set(species)
    binary, origin = prune(base_binary, keep), prune(base_origin, keep)
    notes = []
    for x in pl:
        if x.sp not in keep:
            notes.append(f"placement of {x.sp} skipped: not ticked")
            continue
        if not x.tipset <= tips(binary) or not x.tipset <= tips(origin):
            notes.append(f"placement of {x.sp} skipped: sister tips {sorted(x.tipset)} not on the tree")
            continue
        try:                                        # both or neither: the two trees never diverge
            new_binary = add_sister(binary, x.tipset, x.sp)
            new_origin = carry_to_origin(origin, x.tipset, x.sp)
        except ValueError as e:
            notes.append(f"placement of {x.sp} skipped: {e}")
        else:
            binary, origin = new_binary, new_origin
    return binary, origin, notes


def missing(base_binary: str, species: List[str], pl: List[Placement]) -> List[str]:
    built = tips(build_trees(base_binary, base_binary, species, pl)[0])
    return [s for s in species if s not in built]
