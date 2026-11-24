#!/usr/bin/env python3
"""Build druid's default species tree: the `latest` Holozoa tree (one-child nodes collapsed), its
ctenophores replaced by v3's (Whelan 2017 topology), v3-only and chromo94-only tips grafted beside
their sisters with no split their source does not make (a polytomy where the backbone holds
relatives the source lacks), the planarian clade resolved. Dev tool, not shipped:
`python3 tools/build_species_tree.py --out-dir DIR` writes
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
from druid.sptree import add_sister  # noqa: E402

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


def _collapse_unary(newick: str) -> Tuple[str, int]:
    """(newick, count) with every one-child node removed (latest has 5; GeneRax cannot parse a
    species tree with them, final review 24/11/2026): the child takes the node's place, and its
    name when the child is an unnamed inner node."""
    t = _load(newick)
    n = 0
    for node in list(t.traverse("postorder")):
        if len(node.children) != 1:
            continue
        child = node.children[0]
        if node.name and not child.is_leaf() and not child.name:
            child.name = node.name
        n += 1
        if node.up is None:                             # a one-child root: the child is the root
            child.detach()
            child.dist = node.dist
            t = child
        else:
            node.delete(prevent_nondicotomic=False, preserve_branch_length=True)
    return _dump(t), n


def _some(names, most: int = 8) -> str:
    s = sorted(names)
    return ",".join(s) if len(s) <= most else f"{','.join(s[:most])},... ({len(s)} tips)"


def _graft_binary(current: str, t: Tree, m, sis: Set[str], stips: Set[str], tip: str, label: str,
                  notes: List[str]) -> str:
    """`tip` is the sister of `sis` in its source (a binary source parent); `m` is the MRCA of `sis`
    in `t` (= `current`). Restricted to the source's tips (`stips`), the output must say what the
    source says and no more (final review #4, 24/11/2026): `tip` becomes one more child of the
    highest node H above `m` whose source tips are still exactly `sis` (no claim about H's
    backbone-only tips; `sis` stays a clade via `m`), or `m`'s new sister when H is `m`. When `m`
    holds other source tips, the backbone wins and the conflict is reported."""
    extra = (_leaves(m) & stips) - sis
    if extra:
        if len(m.children) > 2:                         # inside one of the backbone's polytomies
            m.add_child(name=tip, dist=1)
            out, where = _dump(t), "one more child of their MRCA (a polytomy)"
        else:
            out, where = add_sister(current, frozenset(_leaves(m)), tip), "sister of their MRCA"
        notes.append(f"conflict: {tip} ({label}: sister of {_some(sis)}) placed as {where}; "
                     f"the backbone groups {_some(sis)} with {_some(extra)}")
        return out
    h = m
    while h.up is not None and (_leaves(h.up) & stips) == sis:
        h = h.up
    if h is m:
        return add_sister(current, frozenset(_leaves(m)), tip)
    h.add_child(name=tip, dist=1)
    notes.append(f"polytomy graft: {tip} ({label}: sister of {_some(sis)}) joins the node over "
                 f"{_some(_leaves(h) - {tip})} as one more child")
    return _dump(t)


def _graft(current: str, src: Tree, tip: str, placed: Set[str], label: str, notes: List[str],
           climb: bool = False) -> str:
    """Place `tip` beside its sister (leaves of its source parent, still placed): a binary source
    parent through _graft_binary. With `climb`, a tip whose sister is not placed yet (a cherry of
    two new tips) goes beside the nearest source ancestor's placed tips instead (a binary one
    through _graft_binary too: chromo94's ((Aphvas,Aphrbe),Oopmin) on latest's ((Avas,Oopmin),Clad)
    gives ((Avas,Oopmin),Clad,(Aphvas,Aphrbe)))."""
    parent = src.search_nodes(name=tip)[0].up
    sis = (_leaves(parent) - {tip}) & placed
    while climb and not sis and parent.up is not None:
        parent = parent.up
        sis = (_leaves(parent) - {tip}) & placed
    if not sis:
        return ""
    t = _load(current)
    host = t.get_common_ancestor(*sorted(sis)) if len(sis) > 1 else (t & next(iter(sis)))
    if len(parent.children) == 2:
        return _graft_binary(current, t, host, sis, _leaves(src), tip, label, notes)
    if len(sis) == 1:
        return add_sister(current, frozenset(sis), tip)
    host.add_child(name=tip, dist=1)                    # a source polytomy stays one
    return _dump(t)


def _add_missing(current: str, source: str, label: str = "source") -> Tuple[str, List[str]]:
    """(current with every `source` tip it lacks grafted, the polytomy-graft / conflict lines)."""
    src = _load(source)
    notes: List[str] = []
    order = [n.name for n in src.iter_leaves()]
    placed = _leaves(_load(current))
    todo = [x for x in order if x not in placed]
    while todo:
        left = []
        for tip in todo:
            out = _graft(current, src, tip, placed, label, notes)
            if out:
                current, placed = out, placed | {tip}
            else:
                left.append(tip)
        if len(left) == len(todo):                      # only cherries of new tips are left: climb once
            out = _graft(current, src, left[0], placed, label, notes, climb=True)
            if not out:
                raise ValueError(f"cannot place: {left}")
            current, placed = out, placed | {left[0]}
            left = left[1:]
        todo = left
    return current, notes


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


def _name_nodes(cons: str, sources: List[Tuple[str, str]], keep_name: str) -> Tuple[str, List[str]]:
    """Name the consensus nodes from (label, newick) sources in precedence order; the notes list the
    renames and every source name that did not land ("name not placed: <name> (<source>, <reason>)")."""
    t = _load(cons)
    for n in t.traverse():
        if not n.is_leaf() and n.name != keep_name:
            n.name = ""
    used = {n.name for n in t.traverse() if not n.is_leaf() and n.name}
    notes = []
    missed: List[Tuple[str, str, str]] = []
    for label, s in sources:
        st = _load(s)
        stips = _leaves(st)
        for sn in st.traverse("preorder"):
            if sn.is_leaf() or not sn.name or sn.name == keep_name:
                continue
            c = _leaves(sn)
            if len(c) < 2:
                missed.append((sn.name, label, "one-tip clade"))
                continue
            m = t.get_common_ancestor(*sorted(c))
            if _leaves(m) & stips != c:
                missed.append((sn.name, label, "clade not in the consensus"))
                continue
            if m.name:
                missed.append((sn.name, label, f"node already named {m.name}"))
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
    have = {n.name for n in t.traverse() if not n.is_leaf() and n.name}
    notes += list(dict.fromkeys(f"name not placed: {nm} ({label}, {why})"
                                for nm, label, why in missed if nm not in have))
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
    """The first two words, normalised; the whole name when the second is "sp"/"sp." ("Hoilungia sp.
    H4" and "Hoilungia sp. H11" are two species: final review #8, 24/11/2026)."""
    words = [w.strip(string.punctuation).lower() for w in re.split(r"\s+", latin.strip())]
    if len(words) > 1 and words[1] == "sp":
        return " ".join(w for w in words if w)
    return " ".join(w for w in words[:2] if w)


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
    (lat, n1), (v3c, n2), (chc, n3) = (_collapse_unary(s) for s in (latest, v3, chromo))
    cur = _swap_ctenophores(lat, v3c)
    cur, gnotes = _add_missing(cur, chc, "chromo94")    # chromo94 first: richer sponge context than v3
    cur, more = _add_missing(cur, v3c, "v3")
    gnotes += more
    cur, tname = _planarians(cur)
    cur, notes = _name_nodes(cur, [("v3", v3), ("latest", latest), ("chromo94", chromo)], tname)
    t = _load(cur)
    _unit_lengths(t)
    origin = _dump(t)
    binary, npoly = _binary(origin)
    tips = [n.name for n in t.iter_leaves()]
    rep = [f"tips: {len(tips)}", f"one-child nodes collapsed: {n1 + n2 + n3}",
           f"polytomies resolved in the binary tree: {npoly}"]
    rep += gnotes + notes
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
