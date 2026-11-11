"""The Counts heatmap screen (spec docs/superpowers/specs/2026-11-11-druid-counts-heatmap-design.md):
species rows (the species tree's compact cladogram) x numbered group columns, drilled class ->
family -> HG -> OG, plus a Custom OG view.  Reads no files itself: the app passes the family / HG
columns and callbacks for OGs, trees, the OG search and re-reading."""
from __future__ import annotations

from typing import Callable

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Input, Static

from . import counts, model
from .counts import Col

from treeview.keys import KeysScreen

LEVELS = ("class", "family", "hg", "og")
NA = "not available here"
FIXED = 2                                   # cladogram, species label
MIN_QUERY = 3                               # / : shortest query searched
MAX_HITS = 200                              # / : most OGs one search adds to Custom

COUNTS_KEYS = [
    ("Move", [("↑ ↓ ← →", "move the cell cursor"), ("pgup pgdn home end", "page / ends")]),
    ("Drill", [("enter", "into the column: class → family → HG → OG"),
               ("esc", "up one level; at the level it was opened at: close")]),
    ("Look", [("c", "colour: z-score ↔ absolute"),
              ("s", "sort the columns by the cursor row (again: default order)"),
              ("z", "collapse the clade above the cursor row"),
              ("e", "expand every collapsed clade")]),
    ("Trees & OGs", [("t", "gene tree: HG → whole tree, the row's species marked · OG → its MRCA"),
                     ("p", "possvm ↔ possvm_prev (OG and Custom levels)"),
                     ("/", "search OGs (id/name, gene, HG; ≥ 3 characters); enter adds up to "
                           "200 hits to Custom"),
                     ("x", "Custom: drop the cursor's column")]),
    ("Other", [("R", "re-read the counts"), ("?", "this list"), (":q!", "quit druid")]),
    ("Notes", [("", "rows: species tree tips; (not on tree) and Σ are not coloured"),
               ("", "colour z: per column over the tree rows, RdBu; absolute: Blues")]),
]


class CountsScreen(Screen):
    DEFAULT_CSS = """
    CountsScreen #counts { height: 1fr; border: round $primary; }
    CountsScreen #legend { height: 1; }
    CountsScreen #cstatus { height: 1; }
    CountsScreen #csearch { display: none; }
    CountsScreen #csearch.on { display: block; }
    """
    BINDINGS = [
        Binding("escape", "back", "back"),
        Binding("t", "tree", "tree"),
        Binding("c", "colour", "colour"),
        Binding("s", "sort_row", "sort"),
        Binding("z", "collapse", "collapse"),
        Binding("e", "expand", "expand"),
        Binding("p", "source", "source"),
        Binding("slash", "search", "search"),
        Binding("x", "drop", "drop"),
        Binding("R", "reload", "re-read"),
        Binding("question_mark", "keys", "keys"),
    ]

    def __init__(self, cfg, m, fam_cols: "list[Col]", hg_cols: "list[Col]", level: str,
                 scope: "str | None", *, unreadable: int = 0,
                 og_source: "Callable[[str, str], model.HGOgs]",
                 open_tree: "Callable[[str, str, model.OG | None, set], None] | None" = None,
                 og_search: "Callable[[str], list] | None" = None,
                 reload: "Callable[[], tuple] | None" = None,
                 focus_col: "str | None" = None, source: str = "possvm", **kwargs):
        super().__init__(**kwargs)
        if level not in LEVELS + ("custom",):
            raise ValueError(f"unknown level {level!r}")
        self.cfg, self.m = cfg, m
        self.fam_cols, self.hg_cols = fam_cols, hg_cols
        self.level, self.scope = level, scope
        self.unreadable = unreadable
        self.og_source, self.open_tree = og_source, open_tree
        self.og_search, self.reload = og_search, reload
        self.focus_col = focus_col
        self.mode = "z"
        if source not in ("possvm", "possvm_prev"):
            raise ValueError(f"unknown source {source!r}")
        self.source = source                 # the opener's source: focus_col is one of its OGs
        self.cols: "list[Col]" = []
        self.sort_row: "int | None" = None
        self._sort_by: "frozenset | None" = None
        self.custom: "list[tuple[str, model.OG, str]]" = []    # (hg, OG, its own source)
        self.status = ""
        self._stack: list = []               # (level, scope, column id, crumbs) to go back to
        self._crumbs: "list[str]" = [] if level == "custom" else self._opening_crumbs(level, scope)
        self._custom_base: list = []         # Custom as built (each entry keeps its source)
        self._custom_flipped = False         # p at Custom: every entry in its other source
        self._custom_at: dict = {}           # Custom column id -> its entry
        self._og_error = ""
        self._ax = None
        self._grid = None
        self._z: list = []
        self._extra: list = []               # labels of the rows after the tree rows
        self._shown: tuple = ()              # the cell the status line describes

    # ---------------------------------------------------------------- layout

    def compose(self) -> ComposeResult:
        t = DataTable(id="counts", cursor_type="cell", zebra_stripes=False)
        t.fixed_columns = FIXED
        yield t
        yield Static("", id="legend")
        yield Input(placeholder="search OGs: id, name, gene or HG · enter adds to Custom",
                    id="csearch")
        yield Static("", id="cstatus")

    def on_mount(self) -> None:
        self._redraw(focus=self.focus_col)
        if self.unreadable:
            self._say(f"{self.unreadable} files unreadable")
        self.query_one("#counts", DataTable).focus()

    def _say(self, text: str) -> None:
        self.status = text
        self.query_one("#cstatus", Static).update(Text(text))

    @staticmethod
    def _opening_crumbs(level: str, scope: "str | None") -> "list[str]":
        """The crumbs above the level the screen opens at: a class id has no '.', an HG id is
        <family>.HG<n>, so the family is the HG id up to its last '.' (a family id may hold dots)."""
        if level == "family":
            return [scope]
        if level == "hg":
            return [scope.split(".", 1)[0], scope]
        if level == "og":
            fam = scope.rsplit(".", 1)[0]
            return [scope.split(".", 1)[0], fam, scope[len(fam) + 1:]]
        return []

    def _breadcrumb(self) -> str:
        if self.level == "custom":
            srcs = {src for _, _, src in self.custom}
            tail = f" · {srcs.pop()}" if len(srcs) == 1 else " · mixed" if srcs else ""
            return f"Counts · Custom ({len(self.custom)}){tail}"
        return " · ".join(["Counts"] + ([" › ".join(self._crumbs)] if self._crumbs else []))

    # ---------------------------------------------------------------- columns of a level

    def _level_cols(self) -> "list[Col]":
        self._og_error = ""
        if self.level == "class":
            return counts.class_cols(self.fam_cols)
        if self.level == "family":
            return [c for c in self.fam_cols if c.id.startswith(self.scope + ".")]
        if self.level == "hg":
            return [c for c in self.hg_cols if c.id.startswith(self.scope + ".HG")]
        if self.level == "og":
            hgogs = self.og_source(self.scope, self.source)
            if hgogs is None:
                self._og_error = f"no ortholog groups for {self.scope} ({self.source})"
                return []
            if hgogs.error:
                self._og_error = f"{self.scope}: {hgogs.error}"
            return counts.og_cols(hgogs)
        # an OG id in two sources at once gets '@<source>' so every column id is unique
        ids = [og.id for _, og, _ in self.custom]
        self._custom_at, out = {}, []
        for e in self.custom:
            hg, og, src = e
            c = counts.og_cols(model.HGOgs(hg, [og]))[0]
            if ids.count(og.id) > 1:
                c.id = f"{og.id}@{src}"
            self._custom_at[c.id] = e
            out.append(c)
        return out

    def _redraw(self, focus: "str | None" = None, row: "int | None" = None) -> None:
        """Rebuild the table; the cursor goes to column `focus` (an id) or stays where it was."""
        t = self.query_one("#counts", DataTable)
        old = t.cursor_coordinate
        if focus is None and self.cols and FIXED <= old.column < FIXED + len(self.cols):
            focus = self.cols[old.column - FIXED].id
        cols = self._level_cols()
        self._ax = counts.axis(self.m)
        if self._sort_by is not None and self._sort_by not in self._ax.tips:
            self._sort_by = None
        self.sort_row = None if self._sort_by is None else self._ax.tips.index(self._sort_by)
        self.cols = counts.order_cols(cols, by=set(self._sort_by) if self._sort_by else None)
        t.border_title = self._breadcrumb()
        t.clear(columns=True)
        if not self.cols:
            self._grid = None
            t.add_column("", key="nodata")
            t.add_row("no data")
            self.query_one("#legend", Static).update("")
            if self._og_error:
                self._say(self._og_error)
            return
        g = self._grid = counts.grid(self.cols, self._ax)
        self._z = counts.zscores(g.rows)
        zmax = max((abs(v) for r in self._z for v in r), default=0.0) or 1.0
        vmax = max((v for r in g.rows for v in r), default=0)
        w = max(3, len(str(len(self.cols))))
        t.add_column("", key="clado")
        t.add_column("species", key="species")
        for j in range(len(self.cols)):
            t.add_column(Text(str(j + 1), justify="right"), width=w, key=f"c{j}")
        t.add_column(Text("total", justify="right"), key="total")
        for i, vals in enumerate(g.rows):
            cells = []
            for j, v in enumerate(vals):
                bg, fg = counts.cell_colour(v, self._z[i][j], self.mode, zmax, vmax)
                cells.append(Text(counts.fmt_count(v), style=f"{fg} on {bg}", justify="right"))
            t.add_row(self._ax.clado[i], self._ax.labels[i], *cells,
                      Text(str(g.row_totals[i]), justify="right"))
        self._extra = []
        if any(g.off_tree):
            self._extra.append("(not on tree)")
            t.add_row("", "(not on tree)", *[Text(counts.fmt_count(v), justify="right")
                                             for v in g.off_tree],
                      Text(str(sum(g.off_tree)), justify="right"))
        self._extra.append("Σ")
        t.add_row("", "Σ", *[Text(counts.fmt_count(v), justify="right") for v in g.sums],
                  Text(str(sum(g.sums)), justify="right"))
        col = FIXED
        if focus is not None:
            col = next((FIXED + j for j, c in enumerate(self.cols) if c.id == focus), FIXED)
        elif FIXED <= old.column:
            col = min(old.column, FIXED + len(self.cols))
        r = old.row if row is None else row
        t.move_cursor(row=max(0, min(r, t.row_count - 1)), column=col)
        self._show_cell()

    # ---------------------------------------------------------------- cursor -> legend, status

    def _cursor(self) -> "tuple[int, int | None]":
        """(row, column index into self.cols or None)."""
        c = self.query_one("#counts", DataTable).cursor_coordinate
        j = c.column - FIXED
        return c.row, (j if 0 <= j < len(self.cols) else None)

    def _row_species(self, i: int) -> "set[str]":
        """Species codes of table row i: a tree row's tips; (not on tree): the off-tree codes."""
        ax, g = self._ax, self._grid
        if i < len(ax.tips):
            return set(ax.tips[i])
        if self._extra[i - len(ax.tips)] == "(not on tree)":
            return set(g.off_codes)
        return set()

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        """A cursor move; the highlight a redraw posts (same cell) keeps the key's status."""
        if tuple(self.query_one("#counts", DataTable).cursor_coordinate) != self._shown:
            self._show_cell()

    def _show_cell(self) -> None:
        self._shown = tuple(self.query_one("#counts", DataTable).cursor_coordinate)
        if self._grid is None:
            return
        i, j = self._cursor()
        self._legend(j)
        ax, g = self._ax, self._grid
        ntree = len(ax.tips)
        if i < ntree:
            who = ax.labels[i]
        else:
            who = self._extra[i - ntree]
            if who == "(not on tree)":
                who += ": " + ", ".join(f"{sp} {n}" for sp, n in
                                        sorted(g.off_codes.items(), key=lambda kv: (-kv[1], kv[0])))
        if j is None:
            n = g.row_totals[i] if i < ntree else (
                sum(g.off_tree) if self._extra[i - ntree] == "(not on tree)" else sum(g.sums))
            self._say(f"{who} · {n} genes over {len(self.cols)} columns")
            return
        c = self.cols[j]
        if i < ntree:
            self._say(f"{c.label} · {who} · {g.rows[i][j]} genes · z {self._z[i][j]:.1f}")
        elif self._extra[i - ntree] == "Σ":
            self._say(f"{c.label} · Σ · {g.sums[j]} genes")
        else:
            self._say(f"{c.label} · {who} · {g.off_tree[j]} genes")

    def _legend(self, j: "int | None") -> None:
        width = max(10, self.size.width)
        t = Text()
        for k in range(j or 0, len(self.cols)):
            piece = f"{k + 1} {self.cols[k].label}"
            sep = "  " if t.plain else ""
            if t.plain and len(t.plain) + len(sep) + len(piece) > width:
                break
            t.append(sep)
            t.append(piece, style="bold" if k == j else "")
        self.query_one("#legend", Static).update(t)

    # ---------------------------------------------------------------- drill

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        event.stop()
        self.action_drill()

    def action_drill(self) -> None:
        if self.level in ("og", "custom"):
            self._say("bottom level · t opens the tree")
            return
        _, j = self._cursor()
        if j is None:
            self._say("enter: on a group column")
            return
        cid = self.cols[j].id
        self._stack.append((self.level, self.scope, cid, list(self._crumbs)))
        # an HG crumb is shown without its family: the family is the crumb before it
        self._crumbs.append(cid[len(self.scope) + 1:] if self.level == "hg" else cid)
        self.level = LEVELS[LEVELS.index(self.level) + 1]
        self.scope = cid
        self._sort_by = None
        self._redraw(row=0)
        self.query_one("#counts", DataTable).move_cursor(column=FIXED)
        self._show_cell()

    def action_back(self) -> None:
        box = self.query_one("#csearch", Input)
        if box.has_class("on"):
            box.remove_class("on")
            self.query_one("#counts", DataTable).focus()
            return
        if not self._stack:
            self.app.pop_screen()
            return
        self.level, self.scope, cid, self._crumbs = self._stack.pop()
        self._sort_by = None
        self._redraw(focus=cid)

    # ---------------------------------------------------------------- look

    def action_colour(self) -> None:
        self.mode = "abs" if self.mode == "z" else "z"
        self._redraw()
        self._say("colour: absolute" if self.mode == "abs" else "colour: z-score")

    def action_sort_row(self) -> None:
        if self._grid is None:
            return
        i, _ = self._cursor()
        if i >= len(self._ax.tips):
            self._say("s: species rows only")
            return
        tips = self._ax.tips[i]
        self._sort_by = None if self._sort_by == tips else tips
        self._redraw(focus=None)
        self.query_one("#counts", DataTable).move_cursor(column=FIXED)
        self._say(f"sorted by {self._ax.labels[i]}" if self._sort_by else "default order")

    def action_collapse(self) -> None:
        ax = self._ax
        i, _ = self._cursor()
        if self._grid is None or i >= len(ax.leaves):
            self._say("z: species rows only")
            return
        leaf = ax.leaves[i]
        msg = counts.collapse_up(self.m, leaf)
        if msg:
            self._say(msg)
            return
        p = self.m.parent[leaf]
        new = counts.axis(self.m)
        self._redraw(row=new.leaves.index(p) if p in new.leaves else i)

    def action_expand(self) -> None:
        self.m.collapsed.clear()
        self._redraw()
        self._say("every clade expanded")

    # ---------------------------------------------------------------- trees and OGs

    def action_tree(self) -> None:
        if self.open_tree is None:
            self._say(NA)
            return
        if self.level in ("class", "family"):
            self._say("t: HG or OG level only")
            return
        if self._grid is None:
            self._say("no data")
            return
        i, j = self._cursor()
        sp = self._row_species(i)
        if self.level == "hg":
            if j is None:
                self._say("t: on an HG column")
                return
            self.open_tree(self.cols[j].id, self.source, None, sp)
            return
        if j is None:
            self._say("t: on an OG column")
            return
        hg, og, src = self._og_at(self.cols[j].id)
        if og is None:
            self._say(f"t: {self.cols[j].id} not found")
            return
        self.open_tree(hg, src, og, sp)

    def _og_at(self, col_id: str) -> "tuple[str, model.OG | None, str]":
        """(hg, OG, its source) of a column; Custom: the entry's own source."""
        if self.level == "custom":
            return self._custom_at.get(col_id, ("", None, self.source))
        hgogs = self.og_source(self.scope, self.source)
        ogs = [] if hgogs is None else hgogs.ogs
        return self.scope, next((og for og in ogs if og.id == col_id), None), self.source

    @staticmethod
    def _other(src: str) -> str:
        return "possvm_prev" if src == "possvm" else "possvm"

    def _custom_label(self) -> str:
        srcs = {src for _, _, src in self.custom}
        return srcs.pop() if len(srcs) == 1 else "mixed" if srcs else self.source

    def action_source(self) -> None:
        if self.level not in ("og", "custom"):
            self._say("p: OG level only")
            return
        self.source = self._other(self.source)
        msg = f"source: {self.source}"
        if self.level == "custom":
            base, none = self._custom_base, 0
            self._custom_flipped = not self._custom_flipped
            if self._custom_flipped:
                self.custom, none = self._custom_in(base)
            else:
                self.custom = list(base)             # back to the list as built, exactly
            msg = (f"{self._custom_label()}: {none} of {len(base)} OGs have no counterpart"
                   if none else f"source: {self._custom_label()}")
        self._sort_by = None
        self._redraw()
        if not self._og_error:
            self._say(msg)

    def _custom_in(self, base: list) -> "tuple[list, int]":
        """Custom with every entry in the other source of its own: per OG of `base`, the OGs of
        its HG there that share a gene; int = OGs of `base` with no such OG (csv missing /
        unreadable, or no gene shared)."""
        out, seen, cache, none = [], set(), {}, 0
        for hg, og, src in base:
            tgt = self._other(src)
            if (hg, tgt) not in cache:
                h = self.og_source(hg, tgt)
                cache[(hg, tgt)] = [] if h is None or h.error else h.ogs
            genes = {mb.gene for mb in og.genes}
            hits = [o for o in cache[(hg, tgt)] if genes & {mb.gene for mb in o.genes}]
            none += not hits
            for o in hits:
                if (hg, o.id, tgt) not in seen:
                    seen.add((hg, o.id, tgt))
                    out.append((hg, o, tgt))
        return out, none

    def action_search(self) -> None:
        if self.og_search is None:
            self._say(NA)
            return
        box = self.query_one("#csearch", Input)
        box.value = ""
        box.add_class("on")
        box.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        box = self.query_one("#csearch", Input)
        box.remove_class("on")
        self.query_one("#counts", DataTable).focus()
        q = event.value.strip()
        if not q:
            return
        if len(q) < MIN_QUERY:
            self._say(f"type at least {MIN_QUERY} characters")
            return
        hits = self.og_search(q)
        if hits is None:
            self._say("OGs still loading")
            return
        if not hits:
            self._say(f"no OGs match {q}")
            return
        hits = [h if len(h) == 3 else (*h, self.source) for h in hits]   # (hg, OG[, source])
        have = {(hg, og.id, src) for hg, og, src in self.custom}
        new = [h for h in hits if (h[0], h[1].id, h[2]) not in have]
        n_new = len(new)
        new = new[:MAX_HITS]
        self.custom.extend(new)
        if self.level != "custom":
            self._stack.append((self.level, self.scope, None, list(self._crumbs)))
            self.level, self.scope = "custom", None
        self._custom_base, self._custom_flipped = list(self.custom), False
        self._sort_by = None
        self._redraw()
        if n_new > MAX_HITS:
            self._say(f"{MAX_HITS} of {n_new} hits shown")
        else:
            self._say(f"{len(new)} OGs added to Custom ({len(self.custom)})")

    def action_drop(self) -> None:
        if self.level != "custom":
            self._say("x: Custom only")
            return
        _, j = self._cursor()
        if j is None:
            self._say("x: on a column")
            return
        cid = self.cols[j].id
        e = self._custom_at.get(cid)
        self.custom = [x for x in self.custom if x is not e]
        self._custom_base, self._custom_flipped = list(self.custom), False   # an edit rebases Custom here
        self._redraw()
        self._say(f"dropped {cid}")

    # ---------------------------------------------------------------- other

    def action_reload(self) -> None:
        if self.reload is None:
            self._say(NA)
            return
        self._say("reading counts …")
        self._reload_bg()

    @work(thread=True, exclusive=True, group="counts_reload")
    def _reload_bg(self) -> None:
        try:
            out = self.reload()
        except Exception as e:                       # shown, never kills the screen
            self.app.call_from_thread(self._say, f"R: {type(e).__name__}: {e}")
            return
        self.app.call_from_thread(self._reloaded, *out)

    def _reloaded(self, fam_cols, hg_cols, bad) -> None:
        self.fam_cols, self.hg_cols, self.unreadable = fam_cols, hg_cols, bad
        self._redraw()
        if not self._og_error:
            self._say(f"counts re-read · {bad} files unreadable" if bad else "counts re-read")

    def action_keys(self) -> None:
        self.app.push_screen(KeysScreen("Counts keys", COUNTS_KEYS))
