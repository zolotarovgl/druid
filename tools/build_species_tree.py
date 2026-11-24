#!/usr/bin/env python3
"""Build druid's default species tree: the `latest` Holozoa tree, its ctenophores replaced by v3's
(Whelan 2017 topology), v3-only and chromo94-only tips grafted beside their sisters, the planarian
clade resolved. Dev tool, not shipped: `python3 tools/build_species_tree.py --out-dir DIR` writes
species_tree.newick (polytomous origin) and species_tree.binary.newick; `--check DIR` verifies DIR
against a fresh build (exit 1 on a difference). Inputs: tools/species_tree/inputs/ (see README there)."""
from __future__ import annotations

import argparse
import re
import string
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

from ete3 import Tree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from druid.sptree import add_sister, carry_to_origin  # noqa: E402

PLANARIANS = "((((Smed,Spol),(Djap,Dugjap)),Gtig),Pnig);"
INPUTS = ROOT / "tools" / "species_tree" / "inputs"
CHROMO = ROOT / "druid" / "data" / "species_tree.chromo94.newick"
TAXONOMY = ROOT / "druid" / "data" / "genome_sources.tsv"
CTEN = ("Eupdun", "Mlei")
TRICLAD = ("Smed", "Dugjap")


def _load(s: str) -> Tree:
    return Tree(s.strip(), format=1)


def _dump(t: Tree) -> str:
    return t.write(format=1, format_root_node=True)


def _leaves(n) -> Set[str]:
    return {x.name for x in n.iter_leaves()}


def clades(newick: str, keep: set) -> Set[frozenset]:
    """Non-trivial clades (2 <= size < |keep|) of the tree pruned to `keep`."""
    t = _load(newick)
    kept = [n for n in t.iter_leaves() if n.name in keep]
    t.prune(kept)
    return {frozenset(_leaves(n)) for n in t.traverse() if not n.is_leaf() and 2 <= len(_leaves(n)) < len(kept)}


def _swap_ctenophores(latest: str, v3: str) -> str:
    t, v = _load(latest), _load(v3)
    a, b = t.get_common_ancestor(*CTEN), v.get_common_ancestor(*CTEN)
    la, lb = _leaves(a), _leaves(b)
    if la != lb:
        raise ValueError(f"ctenophore tips differ: only in latest {sorted(la - lb)}, only in v3 {sorted(lb - la)}")
    parent = a.up
    a.detach()
    b.detach()
    parent.add_child(b)
    return _dump(t)


def _graft(current: str, src: Tree, tip: str, placed: Set[str], climb: bool = False) -> str:
    """Place `tip` beside its sister (leaves of its source parent, still placed). With `climb`, a
    tip whose sister is not placed yet (a cherry of two new tips) goes beside the nearest source
    ancestor's placed tips instead."""
    parent = src.search_nodes(name=tip)[0].up
    sis = (_leaves(parent) - {tip}) & placed
    while climb and not sis and parent.up is not None:
        parent = parent.up
        sis = (_leaves(parent) - {tip}) & placed
    if not sis:
        return ""
    t = _load(current)
    host = t.get_common_ancestor(*sorted(sis)) if len(sis) > 1 else (t & next(iter(sis)))
    exact = _leaves(host) == sis
    if len(parent.children) == 2:
        if exact or len(host.children) > 2:             # a clade, or inside one of latest's polytomies
            return carry_to_origin(current, frozenset(sis), tip)
        return add_sister(current, frozenset(_leaves(host)), tip)   # host holds extra tips: keep the source clade intact
    if len(sis) == 1:
        return add_sister(current, frozenset(sis), tip)
    host.add_child(name=tip, dist=1)                    # a source polytomy stays one
    return _dump(t)


def _add_missing(current: str, source: str) -> str:
    src = _load(source)
    order = [n.name for n in src.iter_leaves()]
    placed = _leaves(_load(current))
    todo = [x for x in order if x not in placed]
    while todo:
        left = []
        for tip in todo:
            out = _graft(current, src, tip, placed)
            if out:
                current, placed = out, placed | {tip}
            else:
                left.append(tip)
        if len(left) == len(todo):                      # only cherries of new tips are left: climb once
            out = _graft(current, src, left[0], placed, climb=True)
            if not out:
                raise ValueError(f"cannot place: {left}")
            current, placed = out, placed | {left[0]}
            left = left[1:]
        todo = left
    return current


def _planarians(current: str) -> Tuple[str, str]:
    t = _load(current)
    node = t.get_common_ancestor(*TRICLAD)
    if _leaves(node) != set(TRICLAD):
        raise ValueError(f"MRCA of {TRICLAD} has tips {sorted(_leaves(node))}, expected exactly those two")
    new = _load(PLANARIANS)
    new.name, new.dist = node.name, node.dist
    parent = node.up
    node.detach()
    parent.add_child(new)
    return _dump(t), node.name


def _name_nodes(cons: str, sources: List[str], keep_name: str) -> Tuple[str, List[str]]:
    t = _load(cons)
    for n in t.traverse():
        if not n.is_leaf() and n.name != keep_name:
            n.name = ""
    used = {n.name for n in t.traverse() if not n.is_leaf() and n.name}
    notes = []
    for s in sources:
        st = _load(s)
        stips = _leaves(st)
        for sn in st.traverse("preorder"):
            if sn.is_leaf() or not sn.name or sn.name == keep_name:
                continue
            c = _leaves(sn)
            if len(c) < 2:
                continue
            m = t.get_common_ancestor(*sorted(c))
            if _leaves(m) & stips != c or m.name:           # source clade not intact, or node named
                continue
            name = sn.name
            if name in used:
                k = 2
                while f"{name}.{k}" in used:
                    k += 1
                notes.append(f"renamed {name} -> {name}.{k}")
                name = f"{name}.{k}"
            m.name = name
            used.add(name)
    return _dump(t), notes


def _unit_lengths(t: Tree) -> None:
    for n in t.traverse():
        n.dist = 0 if n.is_root() else 1


def _binary(origin: str) -> Tuple[str, int]:
    t = _load(origin)
    npoly = sum(1 for n in t.traverse() if len(n.children) > 2)
    t.resolve_polytomy(recursive=True, default_dist=0.0)
    return _dump(t), npoly


def _read_tax(path: Path) -> Dict[str, str]:
    out = {}
    for line in Path(path).read_text().splitlines():
        p = line.split("\t")
        if len(p) >= 2 and p[0].strip():
            out[p[0].strip()] = p[1].strip()
    return out


def _binomial(latin: str) -> str:
    words = [w.strip(string.punctuation).lower() for w in re.split(r"\s+", latin.strip())[:2]]
    return " ".join(w for w in words if w)


def species_report(tips: list, taxonomy_tsv: Path, extra_names: dict) -> List[str]:
    names = dict(_read_tax(taxonomy_tsv))
    names.update(extra_names)
    groups: Dict[str, List[str]] = {}
    lines = []
    for code in tips:
        if code not in names:
            lines.append(f"no taxonomy row: {code}")
        else:
            groups.setdefault(_binomial(names[code]), []).append(code)
    for b, codes in sorted(groups.items()):
        if len(codes) > 1:
            lines.append(f"shared binomial '{b}': {', '.join(codes)}")
    return lines


def build(latest: str, v3: str, chromo: str) -> Tuple[str, str, List[str]]:
    cur = _swap_ctenophores(latest, v3)
    cur = _add_missing(cur, v3)
    cur = _add_missing(cur, chromo)
    cur, tname = _planarians(cur)
    cur, notes = _name_nodes(cur, [v3, latest, chromo], tname)
    t = _load(cur)
    _unit_lengths(t)
    origin = _dump(t)
    binary, npoly = _binary(origin)
    tips = [n.name for n in t.iter_leaves()]
    rep = [f"tips: {len(tips)}", f"polytomies resolved in the binary tree: {npoly}"]
    rep += notes
    extra = _read_tax(INPUTS / "planarians.tsv")
    rep += species_report(tips, TAXONOMY, extra)
    return origin, binary, rep


def _fresh():
    return build((INPUTS / "latest_20251014.newick").read_text(), (INPUTS / "v3_origin.newick").read_text(),
                 CHROMO.read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--out-dir", type=Path)
    g.add_argument("--check", type=Path)
    a = ap.parse_args(argv)
    origin, binary, rep = _fresh()
    print("\n".join(rep))
    if a.out_dir:
        a.out_dir.mkdir(parents=True, exist_ok=True)
        (a.out_dir / "species_tree.newick").write_text(origin)
        (a.out_dir / "species_tree.binary.newick").write_text(binary)
        return 0
    bad = [f for f, new in (("species_tree.newick", origin), ("species_tree.binary.newick", binary))
           if not (a.check / f).is_file() or (a.check / f).read_text() != new]
    if bad:
        print(f"differs from a fresh build: {', '.join(bad)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
