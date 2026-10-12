"""The tree behind the viewer: ete3 parses the newick, then the nodes are flattened into arrays
(preorder ids) so layout and collapsing never walk ete3 objects.  No Textual import here."""
from __future__ import annotations

import csv
import hashlib
import io
import re
from pathlib import Path
from typing import Optional

from ete3 import Tree, TreeNode
from rich.color import Color, ColorParseError

_NUM = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")
_BAD_NAME = re.compile(r"[(),:;\[\]\s]")     # newick syntax, and any whitespace other than the plain spaces rename() turns into `_`

# tip colours when no --colours map is given: distinct on dark and light terminals
PALETTE = ["#e6194b", "#3cb44b", "#ffb000", "#4363d8", "#f58231", "#911eb4", "#46c0f0",
           "#f032e6", "#9acd32", "#fa8072", "#008080", "#c38bff", "#a0522d", "#808000",
           "#ff69b4", "#1e90ff"]


def species_of(name: str, sep: str = "_") -> str:
    """Species code of a tip = the text before the first `sep` (phylocli model.species_of)."""
    return name.split(sep, 1)[0] if sep else name


def hash_colour(key: str) -> str:
    """A stable palette colour for a species or group name (same across runs and machines)."""
    return PALETTE[int(hashlib.md5(key.encode()).hexdigest()[:8], 16) % len(PALETTE)]


def load(src) -> Tree:
    """An ete3 tree from a path or newick text (format=1: internal labels kept as names)."""
    text = Path(src).read_text() if isinstance(src, Path) or not str(src).lstrip().startswith("(") \
        else str(src)
    return Tree(text.strip(), format=1)


def load_colours(path) -> dict:
    """species -> colour, row by row.  A two-column row whose second field is a colour (#rrggbb,
    or a name rich accepts) is used as given.  Any other row is species_info (code, Latin name,
    group): the species is coloured by its group, the third column (missing or empty = 'unknown')."""
    out = {}
    with open(path, errors="replace") as fh:
        for line in fh:
            f = [x.strip() for x in line.rstrip("\r\n").split("\t")]
            if not f[0] or f[0].startswith("#"):
                continue
            if len(f) == 2 and _is_colour(f[1]):
                out[f[0]] = f[1]
            else:
                out[f[0]] = hash_colour((f[2] if len(f) > 2 else "") or "unknown")
    return out


def load_meta(path) -> tuple:
    """Tip metadata: (column names, {tip id: [values]}).  A TSV, or a CSV when the name ends in
    `.csv` (any case) and its header has no tab (POSSVM writes tab-separated `.csv`), with a
    header row; the first column is the tip id, the other columns keep their header names.
    Short rows are padded with "", long ones cut to the header; a repeated id keeps its last row.
    OSError when unreadable, ValueError when there is no header."""
    p = Path(path)
    with open(p, newline="", errors="replace") as fh:
        raw = fh.read()
    text = [ln.rstrip("\r") for ln in raw.split("\n")]
    head = next((ln for ln in text if ln.strip()), "")
    if p.suffix.lower() == ".csv" and "\t" not in head:
        lines = [[x.strip() for x in r] for r in csv.reader(io.StringIO(raw, newline=""))]
    else:
        lines = [[x.strip() for x in ln.split("\t")] for ln in text]
    lines = [r for r in lines if any(r)]
    if not lines:
        raise ValueError("no header row")
    cols = lines[0][1:]
    rows = {}
    for r in lines[1:]:
        if r[0]:
            rows[r[0]] = (r[1:] + [""] * len(cols))[:len(cols)]
    return cols, rows


def _is_colour(s: str) -> bool:
    try:
        Color.parse(s)
        return True
    except ColorParseError:
        return False


class TreeModel:
    """Flat preorder arrays of an ete3 tree plus the viewer state (collapsed and contracted
    nodes).  Node id = preorder index; the subtree of i = ids i .. i + size[i] - 1.

    Two kinds of state, and how they combine:
    - `collapsed` (display only): the node is shown as one leaf and its whole subtree is hidden,
      whatever is contracted inside it.
    - `contracted` (internal nodes, never the root): the node is not shown at all; its children
      attach to its nearest non-contracted ancestor (`shown_parent`), making a polytomy, and their
      drawn branch is their own length plus those of the contracted nodes in between
      (`shown_dist`).  Contraction chains.  Contraction wins over collapsing: a contracted node
      that is also in `collapsed` is still removed, its children appear in its place, each
      collapsed if it is itself in `collapsed`.
    `shown_children` is the structure every view and the export use.

    Tip metadata (`meta` = {tip name: [values]} aligned with `meta_cols`, as `load_meta` returns):
    kept for the tips whose name matches exactly (`meta_matched` of them); other rows are ignored.
    Internal nodes and tips without a row read as blanks."""

    def __init__(self, tree: Tree, sep: str = "_", colours: Optional[dict] = None,
                 meta: Optional[dict] = None, meta_cols: Optional[list] = None):
        self.tree, self.sep, self.colours = tree, sep, dict(colours or {})
        nodes = self._nodes = list(tree.traverse("preorder"))    # ete3 nodes by id, for to_newick
        index = {id(n): i for i, n in enumerate(nodes)}
        self.name: list = []
        self.support: list = []          # float, or None when the node has no numeric label
        self.dist: list = []
        self.parent: list = []
        self.children: list = []
        for n in nodes:
            leaf = n.is_leaf()
            nm = n.name or ""
            sup = None
            if not leaf and _NUM.fullmatch(nm):
                sup, nm = float(nm), ""
            self.name.append(nm)
            self.support.append(sup)
            self.dist.append(float(n.dist or 0.0))
            self.parent.append(index[id(n.up)] if n.up is not None else -1)
            self.children.append([index[id(c)] for c in n.children])
        k = len(nodes)
        self.size = [1] * k
        self.ntips = [0] * k
        self.level = [0] * k
        self.depth = [0.0] * k           # summed branch length from the root
        for i in range(k - 1, -1, -1):
            if not self.children[i]:
                self.ntips[i] = 1
            for c in self.children[i]:
                self.size[i] += self.size[c]
                self.ntips[i] += self.ntips[c]
        for i in range(1, k):
            p = self.parent[i]
            self.level[i] = self.level[p] + 1
            self.depth[i] = self.depth[p] + self.dist[i]
        self.collapsed: set = set()
        self.contracted: set = set()
        self.has_meta = meta is not None
        self.meta_cols: list = list(meta_cols or [])
        n = len(self.meta_cols)
        self.meta: dict = {}             # tip id -> values, for the tips with a row
        for i in range(k):
            if not self.children[i] and meta and self.name[i] in meta:
                self.meta[i] = (list(meta[self.name[i]]) + [""] * n)[:n]
        self.meta_matched = len(self.meta)
        self.colour_by = ""              # a metadata column, or "" = species colours
        self.highlight: set = set()      # node ids drawn bold underline (an embedding caller's
        #                                  selection, e.g. phylocli's OG members)
        self._tips = {self.name[i]: i for i in range(k) if not self.children[i]}

    def __len__(self) -> int:
        return len(self.name)

    def is_tip(self, i: int) -> bool:
        return not self.children[i]

    def shown_as_leaf(self, i: int) -> bool:
        return self.is_tip(i) or (i in self.collapsed and i not in self.contracted)

    def shown_children(self, i: int) -> list:
        """Children of i as drawn: a contracted child is replaced by its own shown children."""
        if not self.contracted:
            return self.children[i]
        out, stack = [], list(reversed(self.children[i]))
        while stack:
            c = stack.pop()
            if c in self.contracted:
                stack.extend(reversed(self.children[c]))
            else:
                out.append(c)
        return out

    def shown_parent(self, i: int) -> int:
        """The nearest ancestor of i that is not contracted (-1 for the root)."""
        p = self.parent[i]
        while p in self.contracted:
            p = self.parent[p]
        return p

    def shown_dist(self, i: int) -> float:
        """The drawn branch length of i: its own plus those of the contracted nodes above it,
        up to its shown parent."""
        d, p = self.dist[i], self.parent[i]
        while p in self.contracted:
            d += self.dist[p]
            p = self.parent[p]
        return d

    def shown_levels(self) -> list:
        """Level of every node in the shown tree (a contracted node's children take its level)."""
        if not self.contracted:
            return self.level
        lv = [0] * len(self.name)
        for i in range(1, len(self.name)):
            p = self.parent[i]
            lv[i] = lv[p] + (0 if p in self.contracted else 1)
        return lv

    def visible(self) -> list:
        """Visible node ids in preorder (a collapsed node is shown, its subtree is not; a
        contracted node is never shown, its subtree is)."""
        out, i, k = [], 0, len(self.name)
        while i < k:
            if i in self.contracted:
                i += 1
                continue
            out.append(i)
            i += self.size[i] if i in self.collapsed else 1
        return out

    def species(self, i: int) -> str:
        return species_of(self.name[i], self.sep)

    def colour(self, i: int) -> str:
        """By the `colour_by` column's value (hash palette) when set and the tip has one, else by
        species."""
        if self.colour_by:
            v = self.meta_value(i, self.colour_by)
            if v:
                return hash_colour(v)
        sp = self.species(i)
        return self.colours.get(sp) or hash_colour(sp)

    def meta_value(self, i: int, col: str) -> str:
        """Node i's value in metadata column `col`; "" for internal nodes and tips without one."""
        row = self.meta.get(i)
        return row[self.meta_cols.index(col)] if row is not None else ""

    def set_colour_by(self, col: str) -> int:
        """Colour tips by metadata column `col` (stripped); "" goes back to species colours.
        Returns the number of distinct non-empty values in the column (0 for "").  KeyError for an
        unknown column, and nothing changes."""
        col = col.strip()
        if not col:
            self.colour_by = ""
            return 0
        if col not in self.meta_cols:
            raise KeyError(col)
        self.colour_by = col
        k = self.meta_cols.index(col)
        return len({row[k] for row in self.meta.values() if row[k]})

    def toggle(self, i: int) -> None:
        if self.is_tip(i):
            return
        self.collapsed.symmetric_difference_update({i})

    def ancestors(self, i: int) -> list:
        out = []
        while self.parent[i] != -1:
            i = self.parent[i]
            out.append(i)
        return out

    def tip(self, name: str) -> "int | None":
        """Node id of the tip called `name` (exact), None when there is none."""
        return self._tips.get(name)

    def mrca(self, ids) -> int:
        """The deepest node whose subtree holds every id in `ids`; the root when `ids` is empty.
        Uses the preorder layout: the subtree of a is a .. a + size[a] - 1."""
        ids = list(ids)
        if not ids:
            return 0
        a = ids[0]
        for b in ids[1:]:
            while not (a <= b < a + self.size[a]):
                a = self.parent[a]
        return a

    def reveal(self, i: int) -> None:
        """Expand every ancestor of i so that i is visible.  Contraction is left alone: a
        contracted i stays hidden (the view goes to its nearest shown ancestor)."""
        self.collapsed.difference_update(self.ancestors(i))

    def rename(self, i: int, name: str) -> str:
        """Name the internal node i (empty clears it); returns the stored name.  Spaces become `_`.
        ValueError for a tip (tips keep their names) and for a name that newick cannot carry:
        any of ( ) , : ; [ ], or a bare number (it would read back as a support)."""
        if self.is_tip(i):
            raise ValueError("tips keep their names")
        nm = name.strip().replace(" ", "_")
        if _BAD_NAME.search(nm) or _NUM.fullmatch(nm):
            raise ValueError(f"invalid name: {name}")
        self.name[i] = nm
        return nm

    def to_newick(self) -> str:
        """The tree as shown, as newick text (ete3 format 1) with the clade names.  An internal
        node's label is its name if it has one, else its support (`:g`), else empty; tips and
        branch lengths are kept.  Contracted nodes are left out (their children form a polytomy,
        with `shown_dist` lengths); collapsed clades are display only and written in full.
        The names are copied onto the ete3 nodes, so `self.tree` carries them after."""
        for i, n in enumerate(self._nodes):
            if not self.children[i]:
                continue
            n.name = self.name[i] or ("" if self.support[i] is None else f"{self.support[i]:g}")
        # ete3 drops the root's label and length unless asked, and then writes `:0` after an
        # unlabelled root; ask only when the root has something to keep
        keep_root = bool(self._nodes[0].name) or self.dist[0] != 0
        if not self.contracted:
            return self.tree.write(format=1, format_root_node=keep_root)
        out = TreeNode(name=self._nodes[0].name, dist=self.dist[0])   # a fresh tree, as shown
        stack = [(0, out)]
        while stack:
            i, node = stack.pop()
            for c in self.shown_children(i):
                child = TreeNode(name=self._nodes[c].name, dist=self.shown_dist(c))
                node.add_child(child)
                stack.append((c, child))
        # summed lengths carry more digits than the input: ete3's default %0.6g would round them
        # by up to ~5e-6 per branch
        return out.write(format=1, format_root_node=keep_root, dist_formatter="%0.10g")

    def search(self, query: str) -> list:
        """Ids (preorder) whose tip or clade name, or one of whose metadata values, contains
        `query` (case-insensitive)."""
        q = query.lower()
        if not q:
            return []
        return [i for i, n in enumerate(self.name)
                if q in n.lower() or any(q in v.lower() for v in self.meta.get(i, ()))]

    def contract_below_support(self, x: float) -> int:
        """Contract every internal node (not the root) with a support below x, adding to what is
        already contracted; returns how many have a support below x."""
        hit = {i for i in range(1, len(self.name))
               if self.children[i] and self.support[i] is not None and self.support[i] < x}
        self.contracted |= hit
        return len(hit)

    def collapse_single_species(self) -> int:
        """Collapse every maximal shown clade (not the root, not contracted) whose tips are all
        one species; maximal = its shown parent is mixed.  A contracted single-species clade is
        not collapsed: its shown single-species children are."""
        k = len(self.name)
        sp = [None] * k                  # the single species of a node's tips, or "" if mixed
        for i in range(k - 1, -1, -1):
            if self.is_tip(i):
                sp[i] = self.species(i)
            else:
                s = {sp[c] for c in self.children[i]}
                sp[i] = s.pop() if len(s) == 1 and "" not in s else ""
        hit = {i for i in range(1, k) if self.children[i] and sp[i]
               and i not in self.contracted and not sp[self.shown_parent(i)]}
        self.collapsed |= hit
        return len(hit)

    def expand_all(self) -> None:
        """Clear both the collapsed and the contracted nodes."""
        self.collapsed.clear()
        self.contracted.clear()
