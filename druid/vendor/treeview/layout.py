"""Rows of the two views, as pure functions of a TreeModel: [(rich Text, node id)].
No Textual import, so the layout is tested without a UI."""
from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from treeview.model import TreeModel, hash_colour

DIM = "bright_black"


def _fmt(x: float) -> str:
    return f"{x:g}"


def _cut(s: str, width: int) -> str:
    """s cut to `width` characters, the last one `…` when something was dropped."""
    return s if len(s) <= width else s[:max(width - 1, 0)] + "…"


def node_label(m: TreeModel, i: int, mark: bool = True, name_width: int = 40) -> Text:
    """A node's text: tip name (species colour); a collapsed clade `▶ name (n tips)` (no ▶ with
    mark=False: the outline has its own ▸), named by its group when `g` collapsed it (in the
    group's colour while colouring by the group column); an internal node its name and support
    (dim).
    Tip and clade names are cut to `name_width` characters with `…` (the full name is in the
    status line)."""
    t = Text()
    if m.is_tip(i):
        style = m.colour(i) + (" bold underline" if i in m.highlight else "")
        t.append(_cut(m.name[i], name_width), style=style)
        return t
    nm = _cut(m.name[i], name_width)
    if i in m.collapsed:
        if mark:
            t.append("▶ ", style="bold")
        g = m.group.get(i)
        if g:
            style = "bold " + hash_colour(g) if m.colour_by == m.group_column() else "bold"
            t.append(_cut(g[len(m.group_prefix):], name_width), style=style)
        else:
            t.append(nm or "clade", style="bold")
        t.append(f" ({m.ntips[i]} tips)", style=DIM)
        if m.support[i] is not None:
            t.append(f" {_fmt(m.support[i])}", style=DIM)
        return t
    if nm:
        t.append(nm, style="bold")
    if m.support[i] is not None:
        t.append((" " if nm else "") + _fmt(m.support[i]), style=DIM)
    return t


MIN_NAME = 12                           # names are cut no shorter than this to fit a narrow view
META_GAP = 2                            # blanks after the widest row, and between columns


def _meta_widths(m: TreeModel) -> list:
    """Width of each metadata column: its name or its longest value over the visible tips,
    whichever is longer, at most m.meta_width."""
    tips = [m.meta[i] for i in m.visible() if i in m.meta]
    return [min(max([len(c)] + [len(r[k]) for r in tips]), m.meta_width)
            for k, c in enumerate(m.meta_cols)]


def _meta_cells(values: list, widths: list) -> str:
    """Values cut to their column's width with `…`, each padded to it (the last one is not)."""
    cells = [_cut(v, w) for v, w in zip(values, widths)]
    padded = [c.ljust(w) for c, w in zip(cells[:-1], widths)] + cells[-1:]
    return (" " * META_GAP).join(padded)


def _row_node(m: TreeModel, key) -> int:
    """The node whose metadata a row carries: a normal row's node, a compact row's leaf."""
    return next(s[0] for s in key if m.shown_as_leaf(s[0])) if isinstance(key, list) else key


def with_meta(m: TreeModel, rows: list) -> list:
    """The metadata columns appended to the rows (in place) when the model has any.  They align
    at x = the widest row + META_GAP: every node row is padded to x (fillers are not), then a
    tip's row (a compact row's leaf) gets its values.  Internal nodes, collapsed clades and tips
    without a row stay blank."""
    if not m.meta_cols:
        return rows
    x = max(t.cell_len for t, _ in rows) + META_GAP
    widths = _meta_widths(m)
    for t, key in rows:
        if key is None:                                    # a filler row
            continue
        i = _row_node(m, key)
        t.append(" " * (x - t.cell_len))
        if i in m.meta:
            t.append(_meta_cells(m.meta[i], widths))
    return rows


def meta_header(m: TreeModel, rows: list) -> Text:
    """The column names line for rows built with meta=True, aligned with their values (empty
    without metadata).  x is read back from any node row: its length less its own cells."""
    if not m.meta_cols:
        return Text()
    widths = _meta_widths(m)
    t, key = next((t, key) for t, key in rows if key is not None)
    i = _row_node(m, key)
    x = t.cell_len - (cell_len(_meta_cells(m.meta[i], widths)) if i in m.meta else 0)
    return Text(" " * x + _meta_cells(m.meta_cols, widths), style="bold")


def outline_rows(m: TreeModel, lengths: bool = True, name_width: int = 40,
                 meta: bool = False) -> list:
    """One row per visible node in preorder: two spaces per level, ▾ open / ▸ collapsed clade,
    then the label and (dim) `:branch length` (summed over contracted nodes above it).
    meta=True: the metadata columns to the right (`with_meta`)."""
    rows, level = [], m.shown_levels()
    for i in m.visible():
        t = Text("  " * level[i])
        if not m.is_tip(i):
            t.append("▸ " if i in m.collapsed else "▾ ", style=DIM)
        else:
            t.append("  ")
        t.append_text(node_label(m, i, mark=False, name_width=name_width))
        if lengths and i != 0:
            t.append(f" :{_fmt(m.shown_dist(i))}", style=DIM)
        rows.append((t, i))
    return with_meta(m, rows) if meta else rows


def clado_order(m: TreeModel) -> list:
    """Visible nodes in drawing order: the first half of a node's children (rounded up), the
    node, the rest; every node gets its own row."""
    out, stack = [], [(0, False)]
    while stack:
        i, emit = stack.pop()
        if emit or m.shown_as_leaf(i):
            out.append(i)
            continue
        ch = m.shown_children(i)
        h = (len(ch) + 1) // 2
        for c in reversed(ch[h:]):
            stack.append((c, False))
        stack.append((i, True))
        for c in reversed(ch[:h]):
            stack.append((c, False))
    return out


def columns(m: TreeModel, order: list, width: int, scaled: bool) -> dict:
    """Column of each visible node.  Unscaled: by level, leaves (tips and collapsed clades)
    aligned at the right (the step per level is at least 1); scaled: by summed branch length, at
    least one column right of the parent.  `width` = columns available for branches.  Both
    follow the shown tree (contracted nodes left out; depth from the root is unchanged by
    contraction)."""
    if scaled:
        deep = max(m.depth[i] for i in order) or 1.0
        x = {}
        for i in sorted(order):                       # preorder: parents first
            p = m.shown_parent(i)
            col = 1 + round(m.depth[i] / deep * max(width - 2, 1))
            x[i] = col if p == -1 else max(col, x[p] + 1)
        return x
    level = m.shown_levels()
    top = max(level[i] for i in order)
    step = max(1, (width - 2) // max(top, 1))
    end = 1 + top * step
    return {i: (end if m.shown_as_leaf(i) else 1 + level[i] * step) for i in order}


def fit_rows(m: TreeModel, view_width: int, width: int, scaled: bool = False, gap: int = 0,
             name_width: int = 40) -> tuple:
    """(branch width, rows) to draw the cladogram with: `width` when the widest row, labels
    included, fits in `view_width` columns, else the largest smaller width (down to 2) that does.
    The rows are those of the chosen width, as `clado_rows(meta=False)` returns them (add the
    metadata columns with `with_meta`); each width tried is laid out once, the chosen one is
    not laid out again.  Metadata columns are not counted (they scroll).  The step per level
    reaches 1 at the smallest widths; when even 2 overruns, the names are cut shorter (`…`, down
    to MIN_NAME characters) until the rows fit, with the branch width 2; when even that overruns
    (a very deep tree), the rows of width 2 with the full `name_width` are returned and the view
    scrolls."""
    built: dict = {}                   # (branch width, name width) -> rows

    def fits(w: int, nw: int = name_width) -> bool:
        built[w, nw] = rows = _clado_rows(m, w, scaled, gap, nw)
        return max(t.cell_len for t, _ in rows) <= view_width
    if width <= 2:
        return width, _clado_rows(m, width, scaled, gap, name_width)
    if fits(width):
        return width, built[width, name_width]
    if not fits(2):
        if name_width <= MIN_NAME or not fits(2, MIN_NAME):
            return 2, built[2, name_width]
        lo, hi = MIN_NAME, name_width      # fits(2, lo), not fits(2, hi)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if fits(2, mid) else (lo, mid)
        return 2, built[2, lo]
    lo, hi = 2, width                  # fits(lo), not fits(hi); row width grows with `width`
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return lo, built[lo, name_width]


def fit_width(m: TreeModel, view_width: int, width: int, scaled: bool = False, gap: int = 0,
              name_width: int = 40) -> int:
    """The branch width of `fit_rows`, without the rows."""
    return fit_rows(m, view_width, width, scaled, gap, name_width)[0]


def clado_rows(m: TreeModel, width: int = 60, scaled: bool = False, gap: int = 0,
               name_width: int = 40, meta: bool = False) -> list:
    """Box-drawn cladogram rows.  `width` = columns for the branches (labels go right of them).
    `gap` filler rows separate consecutive node rows; a filler is (Text, None) and holds only the
    vertical `│` connectors that run through it.  gap=-1 is the compact cladogram (see
    `_compact_rows`): its rows are (Text, [(node id, x0, x1), ...]) instead.
    meta=True: the metadata columns to the right (`with_meta`)."""
    rows = _clado_rows(m, width, scaled, gap, name_width)
    return with_meta(m, rows) if meta else rows


def _clado_rows(m: TreeModel, width: int, scaled: bool, gap: int, name_width: int) -> list:
    if gap < 0:
        return _compact_rows(m, width, scaled, name_width)
    order = clado_order(m)
    step = gap + 1
    row = {i: r * step for r, i in enumerate(order)}
    x = columns(m, order, width, scaled)
    grid = [[" "] * (max(x.values()) + 1) for _ in range(len(order) * step - gap)]
    root = order[0] if len(order) == 1 else 0
    grid[row[root]][0] = "─"
    for i in order:
        if m.shown_as_leaf(i):
            continue
        ch, xi = m.shown_children(i), x[i]
        r0, r1 = row[ch[0]], row[ch[-1]]
        # the bar reaches the node's own row too: with one child (a unifurcation) the node's row
        # lies outside the span of its children
        for r in range(min(r0, row[i]), max(r1, row[i]) + 1):
            grid[r][xi] = "│"
        for k, c in enumerate(ch):
            grid[row[c]][xi] = "┌" if k == 0 else "└" if k == len(ch) - 1 else "├"
            for col in range(xi + 1, x[c]):
                grid[row[c]][col] = "─"
        grid[row[i]][xi] = "┤"
    rows = []
    for k, i in enumerate(order):
        if k:
            rows.extend((Text("".join(line).rstrip()), None)
                        for line in grid[row[i] - gap:row[i]])
        line = grid[row[i]]
        if m.shown_as_leaf(i):
            line[x[i]] = "─"
        t = Text("".join(line).rstrip())
        lab = node_label(m, i, name_width=name_width)
        if lab.plain:
            t.append(" ")
            t.append_text(lab)
        rows.append((t, i))
    return rows


# a compact cell's connectors as a bitmask (up, down, left, right) -> its box character
_U, _D, _L, _R = 1, 2, 4, 8
_BOX = {0: " ", _U: "│", _D: "│", _U | _D: "│", _L: "─", _R: "─", _L | _R: "─",
        _D | _R: "┌", _U | _R: "└", _U | _D | _R: "├", _L | _U | _D: "┤", _L | _D: "┐",
        _L | _U: "┘", _L | _R | _D: "┬", _L | _R | _U: "┴", _L | _R | _U | _D: "┼"}


def _compact_rows(m: TreeModel, width: int, scaled: bool, name_width: int) -> list:
    """The compact cladogram: one row per leaf (tip or collapsed clade), in drawing order.  An
    expanded internal node sits on the middle row of its children's span (rounded up the
    screen), its vertical bar runs from its first child's row to its last, and its junction cell
    is drawn from the connectors that meet there (┤, or ┬ ┴ ┼ where a child's branch leaves on
    the same row).  No internal labels.  Row = (Text, [(node id, x0, x1), ...]) sorted by x0:
    what the cursor highlights for each node on the row, the junction cell of an internal node
    and the label of the leaf."""
    order = clado_order(m)
    leaves = [i for i in order if m.shown_as_leaf(i)]
    row = {i: r for r, i in enumerate(leaves)}
    for i in sorted(order, reverse=True):              # children (higher ids) before parents
        if i not in row:
            ch = m.shown_children(i)
            row[i] = (row[ch[0]] + row[ch[-1]]) // 2
    x = columns(m, order, width, scaled)
    cells = [[0] * (max(x.values()) + 1) for _ in leaves]
    root = 0
    cells[row[root]][0] |= _R
    cells[row[root]][x[root]] |= _L
    stops: list = [[] for _ in leaves]
    for i in order:
        if m.shown_as_leaf(i):
            cells[row[i]][x[i]] |= _L | _R
            continue
        ch, xi = m.shown_children(i), x[i]
        lo, hi = min(row[ch[0]], row[i]), max(row[ch[-1]], row[i])
        for r in range(lo, hi + 1):
            cells[r][xi] |= (_U if r > lo else 0) | (_D if r < hi else 0)
        for c in ch:
            line = cells[row[c]]
            line[xi] |= _R
            for col in range(xi + 1, x[c]):
                line[col] |= _L | _R
            line[x[c]] |= _L
        stops[row[i]].append((i, xi, xi + 1))
    rows = []
    for r, i in enumerate(leaves):
        t = Text("".join(_BOX[v] for v in cells[r]).rstrip())
        lab = node_label(m, i, name_width=name_width)
        if lab.plain:
            x0 = t.cell_len + 1
            t.append(" ")
            t.append_text(lab)
            stops[r].append((i, x0, x0 + len(lab.plain)))
        else:                                          # an unnamed tip: its branch end
            stops[r].append((i, x[i], x[i] + 1))
        rows.append((t, sorted(stops[r], key=lambda s: s[1])))
    return rows
