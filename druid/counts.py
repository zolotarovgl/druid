"""Column data of the Counts heatmap: species x group counts, z-scores, colours.  Pure (no Textual)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from . import core, model  # noqa: F401  (core puts druid/vendor on sys.path)

from treeview import layout, model as tvm


@dataclass
class Col:
    id: str            # class "tfs" · family "tfs.T-box" · HG "tfs.T-box.HG1" · OG "tfs.T-box.HG1.0"
    label: str         # what the legend and status line show (OG: "HG1.0:T/Tbx19")
    counts: dict = field(default_factory=dict)   # {species code: n}, n > 0 only

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _tally(genes: Iterable[str]) -> dict:
    out: dict = {}
    for g in genes:
        sp = model.species_of(g)
        out[sp] = out.get(sp, 0) + 1
    return out


def family_cols(cfg, fams: Iterable[str]) -> "tuple[list[Col], int]":
    """One Col per family with >= 1 gene in <outdir>/search/<fam>.genes.list (blank and '#'
    lines skipped); the int counts files that exist but cannot be read.  An absent list (the
    family is not searched yet) and an empty one are dropped silently."""
    cols: list[Col] = []
    bad = 0
    for fam in fams:
        try:
            with open(cfg.outdir / "search" / f"{fam}.genes.list", errors="replace") as fh:
                genes = [ln.strip() for ln in fh]
        except FileNotFoundError:
            continue
        except OSError:
            bad += 1
            continue
        counts = _tally(g for g in genes if g and not g.startswith("#"))
        if counts:
            cols.append(Col(fam, fam, counts))
    return cols, bad


def hg_cols(cfg, hgs: Iterable[str]) -> "tuple[list[Col], int]":
    """One Col per HG with >= 1 sequence in <outdir>/clusters/<hg>.fasta; int = unreadable files."""
    cols: list[Col] = []
    bad = 0
    for hg in hgs:
        try:
            members = model.read_cluster_members(cfg, hg)
        except OSError:
            bad += 1
            continue
        counts = _tally(m.gene for m in members)
        if counts:
            cols.append(Col(hg, hg, counts))
    return cols, bad


def class_cols(fam_cols: "list[Col]") -> "list[Col]":
    """Sums of families by class (the id up to the first '.'), in first-seen order."""
    by: dict[str, Col] = {}
    for c in fam_cols:
        cl = c.id.split(".", 1)[0]
        tgt = by.setdefault(cl, Col(cl, cl, {}))
        for sp, n in c.counts.items():
            tgt.counts[sp] = tgt.counts.get(sp, 0) + n
    return list(by.values())


def og_cols(hgogs: "model.HGOgs") -> "list[Col]":
    """One Col per ortholog group, label '<HG part>.<n>:<name>' (HG1.0:T/Tbx19)."""
    if hgogs.error:
        return []
    hg_part = hgogs.hg.rsplit(".", 1)[-1]
    return [Col(og.id, f"{hg_part}.{og.id.rsplit('.', 1)[-1]}:{og.name}",
                _tally(m.gene for m in og.genes)) for og in hgogs.ogs]


def order_cols(cols: "list[Col]", by: "set[str] | None" = None) -> "list[Col]":
    """by=None: total desc, then id.  by=set of species: summed count of those species desc,
    ties in the default order."""
    base = sorted(cols, key=lambda c: (-c.total, c.id))
    if not by:
        return base
    return sorted(base, key=lambda c: -sum(n for sp, n in c.counts.items() if sp in by))


def zscores(matrix: "list[list[int]]") -> "list[list[float]]":
    """Per column over the rows given: (v - mean) / sample SD; SD 0 or a single row -> 0.0."""
    nr = len(matrix)
    if nr == 0:
        return []
    nc = len(matrix[0])
    out = [[0.0] * nc for _ in range(nr)]
    if nr < 2:
        return out
    for j in range(nc):
        col = [matrix[i][j] for i in range(nr)]
        mean = sum(col) / nr
        sd = math.sqrt(sum((v - mean) ** 2 for v in col) / (nr - 1))
        if sd == 0:
            continue
        for i in range(nr):
            out[i][j] = (col[i] - mean) / sd
    return out


# ColorBrewer 9-class stops
RDBU = ["#b2182b", "#d6604d", "#f4a582", "#fddbc7", "#f7f7f7", "#d1e5f0", "#92c5de", "#4393c3", "#2166ac"]
BLUES = ["#f7fbff", "#deebf7", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c", "#08306b"]
FG_DARK, FG_LIGHT = "#222222", "#eeeeee"


def _interp(stops: "list[str]", u: float) -> str:
    """Colour at u in [0, 1] along the stops (linear in RGB)."""
    u = min(1.0, max(0.0, u)) * (len(stops) - 1)
    i = min(int(u), len(stops) - 2)
    f = u - i
    a = [int(stops[i][k:k + 2], 16) for k in (1, 3, 5)]
    b = [int(stops[i + 1][k:k + 2], 16) for k in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


def _luminance(hexc: str) -> float:
    def lin(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(int(hexc[k:k + 2], 16)) for k in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def cell_colour(v: int, z: float, mode: str, zmax: float, vmax: int) -> "tuple[str, str]":
    """(bg, fg) hex.  mode 'z': RdBu at z (+zmax red, -zmax blue); 'abs': Blues at v / vmax."""
    if mode == "z":
        t = max(-1.0, min(1.0, z / zmax)) if zmax > 0 else 0.0
        bg = _interp(RDBU, (1 - t) / 2)
    elif mode == "abs":
        bg = _interp(BLUES, v / vmax if vmax > 0 else 0.0)
    else:
        raise ValueError(f"unknown colour mode {mode!r}")
    return bg, FG_DARK if _luminance(bg) > 0.45 else FG_LIGHT


def fmt_count(v: int) -> str:
    return "·" if v == 0 else "99+" if v > 99 else str(v)


# ---------------------------------------------------------------- species axis

def load_species_model(cfg) -> "tvm.TreeModel":
    """TreeModel of params.SPECIES_TREE; OSError / ValueError with a message when unset, missing or bad."""
    path = (getattr(cfg, "params", None) or {}).get("SPECIES_TREE")
    if not path:
        raise ValueError("SPECIES_TREE is not set")
    try:
        tree = tvm.load(path)
    except OSError as e:
        raise OSError(f"species tree {path}: {e}") from e
    except Exception as e:
        raise ValueError(f"species tree {path}: cannot parse ({e})") from e
    if len(tree.get_leaves()) < 2:
        raise ValueError(f"species tree {path}: fewer than 2 tips")
    return tvm.TreeModel(tree, sep="_")


@dataclass
class Axis:
    leaves: list      # node id per shown leaf, drawing order
    labels: list      # tip name, or "<first tip>… (k spp.)"
    tips: list        # frozenset of tip names per row
    clado: list       # clado_rows(m, gap=-1) branches only (no tip name), per row


def _tip_names(m, i: int) -> list:
    return [m.name[j] for j in range(i, i + m.size[i]) if m.is_tip(j)]


def axis(m) -> Axis:
    leaves = [i for i in layout.clado_order(m) if m.shown_as_leaf(i)]
    labels, tips = [], []
    for i in leaves:
        names = _tip_names(m, i)
        tips.append(frozenset(names))
        labels.append(names[0] if m.is_tip(i) else f"{names[0]}… ({len(names)} spp.)")
    # the label column shows the name: keep only the branches, at most CLADO_WIDTH columns
    clado = [_branches(t) for t, _ in layout.clado_rows(m, width=CLADO_WIDTH, gap=-1)]
    return Axis(leaves, labels, tips, clado)


CLADO_WIDTH = 24
_BOX_CHARS = frozenset(layout._BOX.values())


def _branches(t):
    """The cladogram row up to its last box-drawing cell (the tip label after it dropped)."""
    s = t.plain
    k = 0
    while k < len(s) and s[k] in _BOX_CHARS:
        k += 1
    return t[:len(s[:k].rstrip())]


@dataclass
class Grid:
    rows: list          # rows[i][j] = count of column j over ax.tips[i]
    off_tree: list      # per column: genes of species in no tip
    off_codes: dict     # species code -> count, over all columns
    sums: list          # per column: all genes
    row_totals: list    # per row: total over the columns


def grid(cols: list, ax: Axis) -> Grid:
    on = set().union(*ax.tips) if ax.tips else set()
    rows = [[sum(c.counts.get(sp, 0) for sp in t) for c in cols] for t in ax.tips]
    off_tree, off_codes = [], {}
    for c in cols:
        n = 0
        for sp, k in c.counts.items():
            if sp not in on:
                n += k
                off_codes[sp] = off_codes.get(sp, 0) + k
        off_tree.append(n)
    return Grid(rows, off_tree, off_codes, [c.total for c in cols], [sum(r) for r in rows])


def collapse_up(m, leaf: int) -> "str | None":
    """z: collapse the parent of a shown leaf (a collapsed clade is expanded first).  The root is
    never collapsed: returns "whole tree" and changes nothing; None on success."""
    p = m.parent[leaf]
    if p <= 0:
        return "whole tree"
    m.collapsed.discard(leaf)
    m.collapsed.add(p)
    return None
