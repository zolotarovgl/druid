"""phylo tui: interactive view of step1 + step2 progress (Textual). Imported only by `phylo tui`."""
from __future__ import annotations

import collections
import math
import re
from datetime import datetime
from pathlib import Path

from rich.markup import escape
from rich.measure import Measurement
from rich.text import Text
from textual import events, work
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, ScrollableContainer, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static, TextArea
from textual.worker import get_current_worker

from druid import core, history, model, paths, setup_state, step1run
from druid.common import fmt_mem, fmt_time
from treeview import widget as tv_widget       # vendored: core puts druid/vendor on sys.path
from treeview.keys import KeysScreen


def load_raw() -> dict:
    """The raw druid.yaml (same path logic as `druid submit`); written into each run dir."""
    return paths.read_raw()

FILTERS = ("actionable", "failed", "ready", "running", "blocked", "done")
TABS = ("jobs", "results", "setup")   # first-screen tabs, in tab order (Setup: druid.setup_tui)
ACTIONABLE = ("failed", "ready")      # the "actionable" filter shows failed + ready HGs
PANE_TITLES = {"#overview": "Overview", "#rtab": "Results", "#stages": "1 Stages", "#hgs": "2 HGs",
               "#arrays": "3 Arrays", "#detail": "4 Detail",
               "#res": "Results", "#ogs": "OGs", "#members": "members", "#species_box": "species"}
STATE_STYLE = {"done": "green", "running": "cyan", "ready": "yellow", "failed": "red",
               "blocked": "bright_black"}
# Stages the TUI shows (overview columns, stages panel, HG-view data): search/cluster in front.
TUI_STAGES = core.STAGES
OV_SEP = "│"
# Overview stage columns: step1 (families) | step2 (HGs); None = the one-character separator column.
OV_COLUMNS = [*core.FAMILY_STAGES, None, *core.HG_STAGES]
# The block names (step 1 / step 2) are a line above the table, #ovsteps, not part of the column
# labels (Grygoriy, 02/11/2026; was a second header row since 09/10/2026).


def ov_column(stage: str) -> int:
    """Overview column of `stage` (after the group and HGs columns, skipping the separator)."""
    return 2 + OV_COLUMNS.index(stage)


def stage_at_column(col: int) -> "str | None":
    """The stage of an overview column; None for group, HGs and the separator (not a stage).
    The one column->stage mapping: enter, cursor restore and the `s` sort use it."""
    return OV_COLUMNS[col - 2] if 2 <= col < 2 + len(OV_COLUMNS) else None


def _short_og(og_id: str) -> str:
    """tfs.T-box.HG1.6 -> HG1.6"""
    return ".".join(og_id.rsplit(".", 2)[-2:])


def _trunc(s: str, n: int = 24) -> str:
    return s if len(s) <= n else s[:n] + "…"


def _wrap(items: list, width: int, indent: str = "  ", sep: str = " · ") -> list[str]:
    """Join `items` with `sep` into lines of at most `width` chars, each indented."""
    lines, cur = [], ""
    for it in items:
        add = it if not cur else cur + sep + it
        if cur and len(indent) + len(add) > width:
            lines.append(indent + cur)
            cur = it
        else:
            cur = add
    if cur:
        lines.append(indent + cur)
    return lines


def species_lines(stats: list, outside: list, width: int = 60) -> list[str]:
    """The species pane: per phylum with members `k/m spp  n genes` and its species (wrapped to
    `width`), then the absent phyla, then member species that are not tips of the species tree."""
    present = [r for r in stats if r.covered]
    absent = [r for r in stats if not r.covered]
    w = max((len(r.phylum) for r in present), default=0)
    out: list[str] = []
    for r in present:
        out.append(f"{r.phylum.ljust(w)}  {r.covered}/{r.total} spp  "
                   f"{r.n_genes} gene{'' if r.n_genes == 1 else 's'}")
        out.extend(_wrap([f"{sp} {n}" for sp, n in r.species], width))
    if absent:
        out.append("absent: " + ", ".join(r.phylum for r in absent))
    if outside:
        w = _wrap([f"{sp} {n}" for sp, n in outside], width, sep=", ")
        out.append("not in species tree: " + w[0].strip())
        out.extend(w[1:])
    return out


def coverage_style(k: int, m: int) -> str:
    """Species coverage k/m as a colour: red below 1/3, yellow below 2/3, else green."""
    f = k / m if m else 0.0
    return "red" if f < 1 / 3 else "yellow" if f < 2 / 3 else "green"


_SPP = re.compile(r"  (\d+)/(\d+) spp  \d+ genes?$")   # a species_lines phylum line


def species_text(text: str) -> Text:
    """The species pane as a Rich Text: each phylum line's `k/m spp` coloured by
    coverage_style, the `absent:` line dim. Styles are spans over the plain text: no species
    code or error message is ever parsed as markup."""
    out = Text(text)
    pos = 0
    for line in text.split("\n"):
        m = _SPP.search(line)
        if line.startswith("absent: "):
            out.stylize("dim", pos, pos + len(line))
        elif m and not line.startswith(" "):
            out.stylize(coverage_style(int(m.group(1)), int(m.group(2))),
                        pos + m.start(1), pos + m.end(2) + len(" spp"))
        pos += len(line) + 1
    return out


def ov_cell(c: tuple, width: int, bar: int, glyphs) -> str:
    """An overview stage cell (Grygoriy, 09/10/2026): `<done>/<total>` right-aligned to
    `width`, then a `bar`-cell bar of done/running/ready/blocked, as Rich markup."""
    n = model.bar_segments(c, bar)
    return (f"{c[0]}/{sum(c)}".rjust(width) + " "
            + "".join(f"[{fg}]{ch * k}[/]" for (ch, fg), k in zip(glyphs, n) if k))


def _possvm_sig(states: dict) -> frozenset:
    """(stage, hg) of every finished POSSVM output: the Results caches go stale when it moves."""
    return frozenset((st, hg) for st in ("possvm", "possvm_prev")
                     for hg, v in states.get(st, {}).items() if v == 0)


def _todo_at(r, stage: str) -> tuple:
    """(ready incl. failed, running) of an overview row at a stage; (-1, -1) when n/a."""
    c = r.per_stage.get(stage)
    return (c[2], c[1]) if c else (-1, -1)


def ov_order(rows: list, sort: "tuple | None", hide: "str | None") -> list:
    """Overview rows as shown: ALL pinned first; `hide` (a stage name) drops rows with nothing
    to do there (ready/failed + running = 0, or n/a); `sort` = (column name, reversed).
    Column names, not indices, so columns added later sort and hide the same way."""
    head = [r for r in rows if r.group == "ALL"]
    rest = [r for r in rows if r.group != "ALL"]
    if hide is not None:
        rest = [r for r in rest if sum(_todo_at(r, hide)) > 0]
    if sort is not None:
        col, rev = sort
        rest.sort(key=lambda r: r.group, reverse=(col == "group" and rev))
        if col == "HGs":
            rest.sort(key=lambda r: r.total, reverse=not rev)
        elif col != "group":
            rest.sort(key=lambda r: _todo_at(r, col), reverse=not rev)
    return head + rest


# ---- header sorting (every listed table) ------------------------------------------------------
# A column of a SortTable: `name` keys the sort state (None = not selectable: the │ separator,
# the selection mark); `label` is the header text ("\n" for the overview's two-row header);
# `numeric` columns sort descending first, the others ascending first.
SortCol = collections.namedtuple("SortCol", "name label numeric", defaults=(False,))


def sort_arrow(numeric: bool, rev: bool) -> str:
    """The direction a sorted column is shown in: ▼ descending, ▲ ascending."""
    return "▼" if numeric != rev else "▲"


def sort_rows(rows: list, sort: "tuple | None", keys: dict) -> list:
    """`rows` in the order of `sort` = (column name, reversed); `keys` = {name: (key, numeric)}.
    Stable (ties keep the incoming order); None or a name not in `keys` = unchanged."""
    if sort is None or sort[0] not in keys:
        return list(rows)
    key, numeric = keys[sort[0]]
    return sorted(rows, key=key, reverse=numeric != sort[1])


OV_COLS = [SortCol("group", "group"), SortCol("HGs", "HGs", True),
           *(SortCol(None, OV_SEP) if st is None else SortCol(st, st, True) for st in OV_COLUMNS)]


def hg_cols(unit: str) -> list:
    """Pane 2 HGs: the selection mark is not sortable; names stay the same for both units."""
    fam = unit == "family"
    return [SortCol(None, " "), SortCol("id", "family" if fam else "HG"),
            SortCol("n", "HGs" if fam else "seqs", True), SortCol("state", "state"),
            SortCol("last", "last"), SortCol("req", "req", True), SortCol("used", "used", True)]


def _mem_time_key(mem: str, time: str) -> tuple:
    """(MB, minutes) of an attempt's memory / time strings, -1 where unparseable ('-')."""
    try:
        mb = core.parse_mem_mb(mem)
    except ValueError:
        mb = -1
    return (mb, model.parse_duration_min(time) or -1)


def _lead_float(s: str) -> float:
    """98.2 of '98.2/97.0'; -inf for NA / empty / nan (sorts last when descending)."""
    try:
        return _finite(float(s.split("/", 1)[0]))
    except ValueError:
        return -math.inf


def _finite(x: "float | None") -> float:
    """A sort key: None and NaN (which breaks `sorted`) become -inf."""
    return -math.inf if x is None or x != x else x


RES_COLS = [SortCol("hg", "HG"), SortCol("ogs", "OGs", True), SortCol("genes", "genes", True),
            SortCol("zero", "⚠", True)]
RES_KEYS = {"hg": (lambda r: model.hg_sort_key(r.hg), False),     # an unreadable HG: -1
            "ogs": (lambda r: -1 if r.error else len(r.ogs), True),
            "genes": (lambda r: -1 if r.error else sum(len(o.genes) for o in r.ogs), True),
            "zero": (lambda r: -1 if r.error else sum(1 for o in r.ogs if o.support == 0), True)}
# no reference-ortholog columns in OGs: the reference is per gene (it differs within 19 % of
# OGs) and is shown per row in `members` (Grygoriy, 09/10/2026)
OG_COLS = [SortCol("og", "OG"), SortCol("genes", "genes", True), SortCol("spp", "spp", True),
           SortCol("support", "support", True), SortCol("name", "name"),
           SortCol("origin", "origin")]
OG_KEYS = {"og": (lambda o: int(o.id.rsplit(".", 1)[1]), False),
           "genes": (lambda o: len(o.genes), True),
           "spp": (lambda o: len({m.species for m in o.genes}), True),
           "support": (lambda o: _finite(o.support), True),
           "name": (lambda o: o.name.lower(), False)}


def _origin_key(o) -> tuple:
    """OGs `origin` sort: oldest (smallest depth) first, then label; no origin (– or ?) last in
    both directions."""
    return (0, o.depth, o.label.lower()) if o is not None else (1, 0, "")


MEM_COLS = [SortCol("gene", "gene"), SortCol("sp", "sp"), SortCol("ref", "ref.orth"),
            SortCol("sup", "sup", True)]
MEM_KEYS = {"gene": (lambda p: p[1].gene, False), "sp": (lambda p: p[1].species, False),   # (i, Member)
            "ref": (lambda p: p[1].ref, False), "sup": (lambda p: _lead_float(p[1].ref_support), True)}


# Results tab (first screen): one row per Jobs group; names = model.OGGroupRow fields.
RT_COLS = [SortCol("group", "group"), SortCol("hgs", "HGs", True),
           SortCol("with_output", "with output", True), SortCol("ogs", "OGs", True),
           SortCol("genes", "genes", True), SortCol("zero", "⚠ sup 0", True)]
RT_KEYS = {c.name: ((lambda r, n=c.name: getattr(r, n)), c.numeric) for c in RT_COLS}


def rt_order(rows: list, sort: "tuple | None", hide: "str | None") -> list:
    """Results tab rows as shown: ALL pinned first; `hide` (a count column name) drops rows
    whose count there is 0; `sort` as for every SortTable."""
    head = [r for r in rows if r.group == "ALL"]
    rest = [r for r in rows if r.group != "ALL"]
    if hide is not None:
        rest = [r for r in rest if getattr(r, hide)]
    return head + sort_rows(rest, sort, RT_KEYS)


class _HeadText(Text):
    """A sortable column's label: it measures 2 cells wider than its text, room for ' ▲'/' ▼',
    so sorting never changes a column's width (rich's public __rich_measure__ protocol).
    `pad` = 0 for a label that already carries the arrow: text + arrow is the same width."""

    def __init__(self, *args, pad: int = 2, **kwargs):
        super().__init__(*args, **kwargs)
        self.pad = pad

    def __rich_measure__(self, console, options):
        m = super().__rich_measure__(console, options)
        return Measurement(m.minimum + self.pad, m.maximum + self.pad)


class SortTable(DataTable):
    """A DataTable with a header cursor (Grygoriy, 09/10/2026): ↑ on the first row enters the
    header, ←/→ move between column names (skipping unnamed columns), enter or s sorts by that
    column (again: reversed), ↓ returns to the first row.  Outside the header, s on a cell table
    sorts by the cursor's column (the overview's s), on a row table it falls through.
    The table owns its sort (`sort` = (column name, reversed) or None, kept across refills) and
    its header labels (▲/▼ after the sorted column, the header cursor reversed); the app orders
    the rows in its fill functions and is told of a new sort by `on_sort(table)`.
    Textual 8.2.8's DataTable has no header cursor: the cursor actions are overridden here, and a
    relabelled header is re-rendered through the public notify_style_update()."""
    BINDINGS = [Binding("s", "sort_here", "sort", show=False)]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cols: list = []
        self.sort_state: "tuple | None" = None   # (column name, reversed); DataTable.sort() stays
        self.header = False                     # header mode
        self.hcol = 0                           # header cursor column
        self.on_sort = None                     # callable(table), set by the app

    def set_cols(self, cols: list) -> None:
        """Replace the columns (and drop the rows); the sort is kept, by column name."""
        self.clear(columns=True)
        self.cols = list(cols)
        if self.header:
            self.hcol = self._near(min(self.hcol, len(self.cols) - 1))
        self.add_columns(*(self._label(i) for i in range(len(self.cols))))

    def _label(self, i: int) -> Text:
        c = self.cols[i]
        text, pad = c.label, 2
        if self.sort_state is not None and c.name is not None and self.sort_state[0] == c.name:
            text += " " + sort_arrow(c.numeric, self.sort_state[1])
            pad = 0                              # the arrow takes the room the padding reserves
        style = "reverse" if self.header and i == self.hcol else ""
        return _HeadText(text, style=style, pad=pad) if c.name is not None else Text(text, style=style)

    def relabel(self) -> None:
        """Show the current sort / header cursor in the labels.  The width never changes (a
        sortable label measures 2 cells more than its text, see _HeadText), so only the caches
        of the rendered header have to go: notify_style_update() is the public method that
        clears them and refreshes (checked on Textual 8.2.8, see README)."""
        for i, col in enumerate(self.ordered_columns[:len(self.cols)]):
            col.label = self._label(i)
        self.notify_style_update()

    def _selectable(self) -> list:
        return [i for i, c in enumerate(self.cols) if c.name is not None]

    def _near(self, i: int) -> int:
        """Column i when selectable, else the next selectable one right of it, else left."""
        sel = self._selectable()
        right = [j for j in sel if j >= i]
        return right[0] if right else (sel[-1] if sel else 0)

    def enter_header(self) -> None:
        self.header = True
        self.hcol = self._near(self.cursor_column if self.cursor_type == "cell" else 0)
        self.show_cursor = False
        self.relabel()
        self.app.refresh_bindings()              # the footer stops advertising row-only keys

    def leave_header(self, to_row: bool = True) -> None:
        self.header = False
        self.show_cursor = True
        if to_row and self.row_count:
            self.move_cursor(row=0, column=self.hcol if self.cursor_type == "cell" else None)
        self.relabel()
        self.app.refresh_bindings()

    def _step(self, d: int) -> None:
        nxt = [j for j in self._selectable() if (j - self.hcol) * d > 0]
        if not nxt:
            return
        self.hcol = nxt[0] if d > 0 else nxt[-1]
        if self.cursor_type == "cell":           # keep the column in view on the wide overview
            self.move_cursor(column=self.hcol)
        self.relabel()

    def sort_by(self, i: int) -> None:
        """Sort by column i: a new column starts in its default direction, the same column
        reverses; an unnamed column (│) does nothing."""
        if not 0 <= i < len(self.cols) or self.cols[i].name is None:
            return
        name = self.cols[i].name
        same = self.sort_state is not None and self.sort_state[0] == name
        self.sort_state = (name, not self.sort_state[1] if same else False)
        self.relabel()
        if self.on_sort is not None:
            self.on_sort(self)

    def action_cursor_up(self) -> None:
        if self.header:
            return
        if self.cursor_row <= 0 and self._selectable():
            self.enter_header()
            return
        super().action_cursor_up()

    def action_cursor_down(self) -> None:
        if self.header:
            self.leave_header()
            return
        super().action_cursor_down()

    def action_cursor_left(self) -> None:
        if self.header:
            self._step(-1)
            return
        super().action_cursor_left()

    def action_cursor_right(self) -> None:
        if self.header:
            self._step(1)
            return
        super().action_cursor_right()

    def action_select_cursor(self) -> None:
        if self.header:                          # enter in the header sorts, never opens
            self.sort_by(self.hcol)
            return
        super().action_select_cursor()

    def action_sort_here(self) -> None:
        if self.header:
            self.sort_by(self.hcol)
        elif self.cursor_type == "cell":
            self.sort_by(self.cursor_column)
        else:
            raise SkipAction()

    def on_blur(self) -> None:
        if self.header:                          # tab away: the header cursor goes too
            self.leave_header(to_row=False)


SPIN_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Spinner(Static):
    """The strip's status line with an animated braille spinner in front (Grygoriy,
    09/10/2026): ~8 frames/s, light over SSH.  stop() empties the line and stops the timer."""

    def __init__(self, **kwargs):
        super().__init__("", markup=False, **kwargs)
        self.text = ""
        self.frame = 0
        self._timer = None

    @property
    def running(self) -> bool:
        return self._timer is not None

    def start(self, text: str) -> None:
        self.text = text
        if self._timer is None:
            self._timer = self.set_interval(1 / 8, self._tick)
        self._draw()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.text = ""
        self.update("")

    def _tick(self) -> None:
        self.frame = (self.frame + 1) % len(SPIN_FRAMES)
        self._draw()

    def _draw(self) -> None:
        self.update(f"{SPIN_FRAMES[self.frame]} {self.text}", layout=False)


# The `?` key screens (Grygoriy, 12/10/2026): one table per view; the help strip is one line.
KEYS = {
    "overview": ("Overview · Jobs", [
        ("Move", [("↑ ↓ ← →", "move · ↑ on the first row: the header (←/→ column, enter/s sort)"),
                  ("tab shift+tab", "Results / Setup tab")]),
        ("Open", [("enter", "open the group at that stage (HG view)"),
                  ("o", "results of the group")]),
        ("Group & sort", [("c", "group by category"), ("f", "group by family"),
                          ("s", "sort by the column"), ("h", "only actionable at the column")]),
        ("Run", [("S", "run step 1: search → cluster (enter dry run · y submit)")]),
        ("Other", [("R", "refresh"), ("?", "this list"), (":q!", "quit druid")]),
        ("Notes", [("", "search/cluster count families, the other stages HGs"),
                   ("", "default view: failed+ready")])]),
    "overview_results": ("Overview · Results tab", [
        ("Move", [("↑ ↓ ← →", "move · ↑ on the first row: the header (←/→ column, enter/s sort)"),
                  ("tab shift+tab", "Setup / Jobs tab")]),
        ("Open", [("enter o", "open the group's Results"),
                  ("t", "trees open from a group's Results (o, then t)")]),
        ("Source", [("p", "possvm ↔ possvm_prev")]),
        ("Group & sort", [("c", "group by category"), ("f", "group by family"),
                          ("s", "sort by the column"), ("h", "hide rows with 0 in the column")]),
        ("Other", [("R", "re-read"), ("?", "this list"), (":q!", "quit druid")]),
        ("Notes", [("⚠", "sup 0 = OGs with support 0 (GeneRax bug case)")])]),
    "hgs": ("HG view", [
        ("Move", [("tab shift+tab", "next / previous pane"), ("↑ ↓", "move"),
                  ("enter", "on stages: pick the stage")]),
        ("Select & act", [("space", "select the HG"), ("a", "select all"), ("A", "unselect all"),
                          ("r", "resubmit the selected"), ("l", "log of the HG")]),
        ("Filter", [("f", "cycle the filter (" + ", ".join(FILTERS) + ")")]),
        ("Other", [("o", "results of the HG's group"), ("esc q", "back to the overview"),
                   ("R", "refresh"), ("?", "this list"), (":q!", "quit druid")]),
        ("Notes", [("", "default filter: failed+ready; the states are "
                    + " · ".join(STATE_STYLE))])]),
    "results": ("Results", [
        ("Move", [("tab shift+tab", "next / previous pane"), ("↑ ↓", "move"),
                  ("s", "sort (↑ on the first row: the header)")]),
        ("Look", [("/", "filter this pane"), ("p", "possvm ↔ possvm_prev"),
                  ("t", "gene tree: HG → whole tree · OG → its MRCA, members marked · "
                        "member → its tip")]),
        ("Other", [("esc q", "clear filters, then back"), ("R", "refresh"), ("?", "this list"),
                   (":q!", "quit druid")]),
        ("Notes", [("⚠", "support 0 = GeneRax bug case; check possvm_prev")])]),
}

# q = esc, quit = :q! (Grygoriy, 23/10/2026). The vendored treeview says "q quit" in its help strip
# and `?` list; druid's TreeScreen says what q does here instead (the vendored copy is not edited).
TREE_HELP = "? keys · esc q back · :q! quit druid"
TREE_KEYS = [(g, [r for r in rows if r[0] != "q"] + ([("q", "same as esc"), (":q!", "quit druid")]
                                                     if g == "Other" else []))
             for g, rows in tv_widget.KEYS]


class DruidTreeScreen(tv_widget.TreeScreen):
    """The vendored TreeScreen with druid's key help (q = esc, :q! quits; PhyloApp.on_event)."""

    def on_mount(self) -> None:                  # the vendored on_mount runs too (Textual MRO)
        self.query_one("#help", Static).update(TREE_HELP)

    def action_keys(self) -> None:
        self.app.push_screen(KeysScreen("treeview keys", TREE_KEYS))


class PhyloApp(App):
    TITLE = "phylocli"
    CSS = """
    #hgview { grid-size: 2 2; grid-columns: 1fr 1fr; grid-rows: 1fr 1fr; }
    #hgview DataTable, #detail { border: round $primary; height: 100%; }
    #strip { height: auto; }
    #helpbox { width: 1fr; height: auto; margin: 0 1; }
    #help { height: auto; }
    #strip #status { height: 1; color: $warning; }
    #ov { height: 1fr; }
    #overview { height: 1fr; border: round $primary; }
    #ovfoot { height: auto; }
    #ovsteps { height: 1; color: $text-muted; }
    #tabbar { height: 1; }
    #rtab { height: 1fr; border: round $primary; }
    #rtab:focus { border: round orange; }
    #rtab.loading { opacity: 40%; }
    #hgview { height: 1fr; }
    #hgview DataTable:focus, #overview:focus { border: round orange; }
    #hgview.loading { opacity: 40%; }
    #resv { height: 1fr; }
    #results { height: 1fr; }
    #res { width: 1fr; }
    #ogs, #rescol { width: 2fr; }
    #res, #ogs, #rescol { height: 100%; }
    #members, #species_box { height: 1fr; }
    #results DataTable, #species_box { border: round $primary; }
    #results DataTable:focus, #species_box:focus { border: round orange; }
    #memfilter { height: 3; }
    #resv.loading { opacity: 40%; }
    #species { width: auto; }
    #resfoot { height: auto; }
    """
    BINDINGS = [
        Binding("escape", "back", "back"),
        Binding("c", "by_category", "category"),
        Binding("f", "cycle_filter", "filter / family"),
        Binding("s", "sort", "sort"),
        Binding("h", "hide", "only actionable"),
        Binding("space", "toggle", "select"),
        Binding("a", "select_all", "select all"),
        Binding("A", "unselect_all", "unselect all"),
        Binding("r", "resubmit", "resubmit"),
        Binding("S", "run_step1", "run step 1"),
        Binding("l", "log", "log"),
        Binding("o", "open_results", "results"),
        Binding("t", "open_tree", "tree"),
        Binding("p", "toggle_source", "possvm/prev"),
        Binding("slash", "member_filter", "filter members"),
        Binding("R", "refresh", "refresh"),
        Binding("question_mark", "keys", "keys"),
    ]   # q = esc and :q! quit: on_event, every screen; plain q is rewritten to escape there, so a
    #     binding of plain q can never fire (ctrl+q stays Textual's quit)

    OV_BAR = 6
    OV_GLYPHS = (("█", "green"), ("▒", "cyan"), ("▓", "yellow"), ("░", "bright_black"))

    def __init__(self, cfg: core.Config, refresh_s: int = 30, raw: "dict | None" = None,
                 start: str = "overview"):
        super().__init__()
        try:                                     # the header names the project directory
            self.title = f"druid · {paths.project_root()}"
        except paths.NoProject:
            self.title = "druid"
        self.cfg = cfg
        self.raw = raw if raw is not None else load_raw()
        self.refresh_s = refresh_s
        self.stage = core.HG_STAGES[0]   # opens on align; search/cluster sit before it
        self.filter = FILTERS[0]
        self._auto_filter = False
        self.selected: set[str] = set()
        self.rows: list = []
        self.by_stage: dict = {}
        self.atts: list = []
        self.nseq: dict[str, int] = {}
        self.view = start
        self.by = "category"
        self.group: "str | None" = None
        self.ov_rows: list = []
        self._ov_inputs: tuple = (set(), {}, set(), {})    # exp, HG states, families, family states
        self.hg_count: dict[str, int] = {}                 # family id -> expected HGs
        self._warned: set = set()               # notifications already shown this session
        self._help_text = ""
        self._status = ""                       # the strip's one-line status area
        self._hist_loading = False
        self.res_from = "overview"              # the view esc returns to from Results
        self.res_group = ""
        self.res_hgs: list[str] = []
        self.res_source: "str | None" = None    # None = model.default_source(), in the worker
        self.res_rows: list = []                # [model.HGOgs] of the open group
        self.res_missing = 0
        self._res_focus: "str | None" = None    # HG to put the Results cursor on after a load
        self._res_gen = 0                       # bumped per load / esc: late snapshots dropped
        self._tree_gen = 0                      # bumped per t / leaving Results: late trees dropped
        self._res_note = ""
        self._res_foot = ""
        self._species_text = ""
        self._flt = {"res": "", "ogs": "", "members": ""}   # `/` filter per Results pane
        self._flt_pane = "members"              # the pane the filter box is editing
        self._universe:"list | None" = None    # species tree tips, read once by the worker
        self._phyla: "dict | None" = None       # species -> phylum, read once by the worker
        self._sp_note = ""                      # why the universe / phyla could not be read
        self._otree = None                      # og_origin.OriginTree, read once by the worker
        self._otree_err = ""                    # why it could not be read ("" = not tried / ok)
        self._origins: dict = {}                # OG id -> Origin | None, of the loaded rows
        self._hg_unit: "str | None" = None                 # unit the #hgs / #arrays headers show
        self._array_rows: list = []
        self.ov_hide: "str | None" = None       # stage name; h
        self.ov_shown: list = []                # ov_rows as displayed (sorted / filtered)
        self.tab = "jobs"                       # first-screen tab: "jobs" | "results" | "setup"; tab
        self.rt_source: "str | None" = None     # Results tab source; None = default_source
        self.rt_hide: "str | None" = None       # Results tab: count column name; h
        self.rt_rows: list = []                 # [model.OGGroupRow], Jobs group order
        self.rt_shown: list = []
        self._og_cache: "dict | None" = None    # {source, rows: {hg: HGOgs}, hgs: frozenset}
        self._rt_gen = 0
        self._og_sig: "frozenset | None" = None  # which POSSVM outputs were done when it was read
        self._rt_note = ""
        self._rt_foot = ""
        self._tab_text = ""
        self._ovsteps_text = ""                 # the step 1 / step 2 line above the overview
        self._res_want: "str | None" = None     # source asked for by the opener (Results tab)
        self._cmd: "str | None" = None          # the `:` command typed so far; None = not in one

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="strip"):                 # all views: key help + status line
            with Vertical(id="helpbox"):
                yield Static("", id="help")
                yield Spinner(id="status")          # Part F: spinner + status text
        with Vertical(id="ov"):
            yield Static("", id="tabbar")
            yield Static("", id="ovsteps")      # step 1 / step 2 over their columns
            yield SortTable(id="overview", cursor_type="cell")
            yield SortTable(id="rtab", cursor_type="cell")
            yield Static("", id="ovfoot")
        with Grid(id="hgview"):
            yield DataTable(id="stages", cursor_type="row")
            yield SortTable(id="hgs", cursor_type="row")
            yield DataTable(id="arrays", cursor_type="row")
            yield Static("", id="detail")
        with Vertical(id="resv"):
            with Horizontal(id="results"):
                yield SortTable(id="res", cursor_type="row")
                yield SortTable(id="ogs", cursor_type="row")
                with Vertical(id="rescol"):
                    yield Input(placeholder="filter members (enter: keep · esc: clear)",
                                id="memfilter")
                    yield SortTable(id="members", cursor_type="row")
                    with ScrollableContainer(id="species_box"):
                        yield Static("", id="species", markup=False)
            yield Static("", id="resfoot")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#stages", DataTable).add_columns("stage", "done", "run", "ready", "blk", "total")
        self.query_one("#overview", SortTable).set_cols(OV_COLS)
        self.query_one("#rtab", SortTable).set_cols(RT_COLS)
        self._set_units(force=True)
        self.query_one("#res", SortTable).set_cols(RES_COLS)
        self.query_one("#ogs", SortTable).set_cols(OG_COLS)
        self.query_one("#members", SortTable).set_cols(MEM_COLS)
        self.query_one("#memfilter").display = False
        for t in self.query(SortTable):          # a header sort reorders that table, in memory
            t.on_sort = self._resorted
        for wid, title in PANE_TITLES.items():   # names in the top-left border, to refer to them
            self.query_one(wid).border_title = title
        self._show_view()
        self.load_bg()
        self.set_interval(self.refresh_s, self.load_bg)
        if self.view == "overview" and self._setup_unfinished():
            self._open_setup()                   # nothing to run yet: start on the Setup tab

    def _setup_unfinished(self) -> bool:
        """Setup is not finished and can still be (Grygoriy, 23/10/2026: `druid tui` brings Setup
        back until it is): not adopted (prepare: locked), the species not locked, and prepare has
        a blocker or has not written params.infasta yet. An error in the check opens on Jobs."""
        try:
            if self.raw.get("prepare") == "locked" or setup_state.species_locked(self.raw, self.cfg):
                return False
            if setup_state.blockers(self.raw, self.cfg, paths.project_root()):
                return True
            fa = self.cfg.params.get("infasta")
            return not fa or not Path(fa).exists()
        except Exception as e:                   # never keeps the TUI from starting
            self._notify_once(f"setup check failed, opening on Jobs: {type(e).__name__}: {e}")
            return False

    # ---- q = esc, :q! quits (Grygoriy, 23/10/2026) --------------------------------------------
    async def on_event(self, event: events.Event) -> None:
        """Before any binding of any screen (the vendored treeview's and the modal ones too): q
        is handed on as esc, `:` starts a command, and inside one `q` `!` exits while any other
        key (esc too) cancels it. A focused Input / TextArea gets these keys as typed text."""
        if isinstance(event, events.Key) and not event.is_forwarded:
            event = self._command_key(event)
            if event is None:
                return
        await super().on_event(event)

    def _command_key(self, event: events.Key) -> "events.Key | None":
        """The key to dispatch in place of `event`; None when it was consumed here. Plain `q` is
        rewritten to escape below, so a binding of plain q can never fire anywhere."""
        if self._cmd is not None:
            if event.key.startswith("ctrl+"):    # ctrl+c / ctrl+q ...: cancel, then Textual's own
                self._cmd = None
                self._show_cmd()
                return event
            typed = self._cmd + (event.character or "\0")      # a key with no character cancels
            if event.key != "escape" and "q!".startswith(typed):
                self._cmd = typed
                if typed == "q!":
                    self.exit()
            else:
                self._cmd = None
            self._show_cmd()
            return None
        if isinstance(self.focused, (Input, TextArea)):
            return event
        if event.key == "colon":
            self._cmd = ""
            self._show_cmd()
            return None
        if event.key == "q":
            return events.Key("escape", "\x1b")
        return event

    def _show_cmd(self) -> None:
        """The command typed so far: on the first screen in the status line, on Setup in its
        bottom line, elsewhere (tree, key list, resubmit) as a notification when it starts."""
        text = "" if self._cmd is None else ":" + self._cmd
        scr = self.screen
        if scr is self.screen_stack[0]:
            self._update_status()
        elif hasattr(scr, "show_command"):
            scr.show_command(text)
        elif text == ":":
            self.notify(": q! quits druid · any other key cancels", timeout=3)

    # ---- data -------------------------------------------------------------------------------
    def _collect(self) -> dict:
        exp = core.expected(self.cfg)
        done_map = core.report_status.done_by_stage(str(self.cfg.outdir), exp)
        lv = model.live(exp)
        known = lv is not None
        lv = lv or {}
        states = model.stage_states(self.cfg, exp, done_map, lv)
        fam_warn: list = []
        fams: set = set()
        if self.cfg.params.get("genefam_info"):
            try:
                fams = core.family_ids(self.cfg)
                fam_warn = core.family_warnings(self.cfg)      # duplicates, name collisions
            except (OSError, ValueError) as e:   # no / unreadable genefam file: warn, go on
                fam_warn = [f"warning: {e}"]
        fstates = model.family_states(self.cfg, fams, lv)
        by = self.by
        ov_rows, _k = model.group_rows(self.cfg, exp, by, states=states, fams=fams, fstates=fstates)
        hg_count = dict(collections.Counter(model.group_key(h, "family") for h in exp))
        snap = dict(ov_rows=ov_rows, by=by, ov_inputs=(exp, states, fams, fstates), known=known,
                    fam_warn=fam_warn, hg_count=hg_count, when=datetime.now(), hg=None)
        if self.view == "hgs":               # the slow part: attempt history, only in the HG view
            for hg in exp:                   # FASTAs are read here, off the UI thread, once
                if not self.nseq.get(hg):
                    self.nseq[hg] = core.nseq(self.cfg, hg)
            atts = history.attempts(self.cfg)
            fatts = history.family_attempts(self.cfg, fams=fams)
            # every applicable stage from ONE attempts read, ONE done scan, ONE squeue call, so
            # that stage changes and the detail panel need no subprocess on a key press
            by_stage = {st: (model.hg_rows(self.cfg, st, exp,
                                           fatts if st in core.FAMILY_STAGES else atts,
                                           done_map, lv, fams=fams)
                             if core.applicable(self.cfg, st) else [])
                        for st in TUI_STAGES}
            arrays, sacct_known = model.array_rows()
            snap["hg"] = dict(atts=atts + fatts, by_stage=by_stage, arrays=arrays,
                              sacct_known=sacct_known)
        return snap

    def load_now(self) -> None:
        self._apply(self._collect())

    @work(thread=True, exclusive=True)
    def load_bg(self) -> None:
        worker = get_current_worker()
        try:
            snap = self._collect()
        except Exception as e:               # keep the old snapshot; never let a worker kill the app
            if not worker.is_cancelled:
                self.call_from_thread(self._notify_once, str(e), "error")
            return
        if worker.is_cancelled:              # superseded by a newer refresh
            return
        self.call_from_thread(self._apply, snap)

    def _notify_once(self, msg: str, severity: str = "warning") -> None:
        """A warning is shown once per session per distinct message (it used to sit in a banner
        that took a line of every view)."""
        if msg in self._warned:
            return
        self._warned.add(msg)
        self.notify(msg, severity=severity, markup=False)

    # key help in the top strip: per view, replaces the footers' legend lines
    def _help_for(self, view: str) -> str:
        key = "overview_results" if view == "overview" and self.tab == "results" else view
        title = KEYS.get(key, KEYS["overview"])[0]
        if key == "overview":
            glyphs = " ".join(f"[{fg}]{ch}[/] {name}" for (ch, fg), name in
                              zip(self.OV_GLYPHS, ("done", "running", "ready/failed", "blocked")))
            return f"[b]{title}[/]  {glyphs}  · ? keys · :q! quit"
        return f"[b]{title}[/]  · ? keys · esc q back · :q! quit"

    def _keys_view(self) -> str:
        if self.view == "overview":
            return "overview_results" if self.tab == "results" else "overview"
        return self.view

    def action_keys(self) -> None:
        title, groups = KEYS[self._keys_view()]
        self.push_screen(KeysScreen(f"phylocli keys · {title}", groups))

    def _update_help(self) -> None:
        self._help_text = self._help_for(self.view)
        self.query_one("#help", Static).update(self._help_text)
        self._update_status()

    def _update_status(self) -> None:
        if self.view == "results":
            text = self._res_note if self._res_note.startswith("loading") else ""
        elif self.view == "hgs":
            text = "loading history…" if self._hist_loading else ""
        elif self.tab == "results" and self._rt_loading():     # the first screen's Results tab
            text = self._rt_note if self._rt_note.startswith("loading") else ""
        else:
            text = ""
        self._status = text
        spin = self.query_one("#status", Spinner)
        if self._cmd is not None:                # a `:` command being typed shows instead
            spin.stop()
            spin.update(":" + self._cmd)
        elif text:
            spin.start(text)                     # turns until the data are applied ...
        else:
            spin.stop()                          # ... or the view no longer waits (esc, tab, R)

    def _apply(self, snap: dict) -> None:
        self._ov_inputs = snap["ov_inputs"]
        self.hg_count = snap["hg_count"]
        if snap["by"] != self.by:            # c/f pressed while this was being collected
            self._regroup()
        else:
            self._fill_overview(snap["ov_rows"])
        self._og_cache_check()
        self._maybe_load_rtab()
        hg = snap["hg"]
        if not snap["known"]:
            self._notify_once("squeue not on PATH: running jobs not detected")
        for w in snap["fam_warn"]:
            self._notify_once(w)
        if hg is not None and not hg["sacct_known"]:
            self._notify_once("sacct not on PATH: task states unknown")
        self._hist_loading = hg is None and self.view == "hgs" and not self.by_stage
        self._update_status()
        if self.view != "results":
            self.sub_title = f"{self.stage} · {self.filter} · {snap['when']:%H:%M:%S}"
        if hg is None:
            return
        self.atts, self.by_stage = hg["atts"], hg["by_stage"]
        self.query_one("#hgview").remove_class("loading")
        self.rows = self.by_stage.get(self.stage, [])
        if self.view == "hgs":
            self._auto_pick_filter()
            self.sub_title = f"{self.stage} · {self.filter} · {snap['when']:%H:%M:%S}"
        # a selected HG that has finished or been queued must not stay selected invisibly:
        # validate() would refuse the whole resubmit over it.  (Blocked HGs stay: they are
        # visible under their filter and test_refresh_keeps_stage_selection_and_cursor pins it.)
        self.selected &= {r.hg for r in self.rows if r.state not in ("done", "running")}
        snap = hg
        self._fill_stages()
        self._array_rows = snap["arrays"]
        self._fill_arrays()
        self._fill_hgs()

    def _fill_arrays(self) -> None:
        ar = self.query_one("#arrays", DataTable)
        keep_row = ar.cursor_row
        ar.clear()
        for i, a in enumerate(self._array_rows):
            c = a.counts
            # keyed by position + run + job: a job id can repeat (fake sbatch, a duplicated
            # jobs.tsv line), and a duplicate DataTable key raises on the UI thread
            ar.add_row(a.job, a.stage, str(a.n), str(c["done"]), str(c["running"]),
                       str(c["pending"]), str(c["failed"]), key=f"{i}:{a.run.name}:{a.job}")
        if self._array_rows:
            ar.move_cursor(row=min(keep_row, len(self._array_rows) - 1))

    def _set_units(self, force: bool = False) -> None:
        """Column labels of #hgs / #arrays follow the open stage: family stages list families
        (second column: the family's HG count), the others HGs (second column: seqs)."""
        unit = "family" if self.stage in core.FAMILY_STAGES else "HG"
        if unit == self._hg_unit and not force:
            return
        self._hg_unit = unit
        self.query_one("#hgs", SortTable).set_cols(hg_cols(unit))   # sort kept (stable names)
        ar = self.query_one("#arrays", DataTable)
        ar.clear(columns=True)
        ar.add_columns("job", "stage", "ids", "done", "run",
                       "pend", "fail")
        if not force:
            self._fill_arrays()

    def visible(self) -> list:
        if self.filter == "actionable":
            rows = [r for r in self.rows if r.state in ACTIONABLE]
        else:
            rows = [r for r in self.rows if r.state == self.filter]
        if self.group is not None:          # search / cluster list families, the rest HGs
            key = model.fam_group_key if self.stage in core.FAMILY_STAGES else model.group_key
            rows = [r for r in rows if key(r.hg, self.by) == self.group]
        return sort_rows(rows, self.query_one("#hgs", SortTable).sort_state, self._hg_keys())

    def _hg_keys(self) -> dict:
        """Sort keys of pane 2 HGs (the second column counts HGs per family on search/cluster)."""
        n = ((lambda r: self.hg_count.get(r.hg, 0)) if self.stage in core.FAMILY_STAGES
             else (lambda r: self.nseq.get(r.hg, 0)))
        return {"id": (lambda r: model.hg_sort_key(r.hg), False), "n": (n, True),
                "state": (lambda r: r.state, False),
                "last": (lambda r: model.bump_reason(r.last) if r.last else "", False),
                "req": (lambda r: _mem_time_key(r.last.mem, r.last.time) if r.last else (-2, -2), True),
                "used": (lambda r: _mem_time_key(r.last.peak_rss, r.last.realtime) if r.last
                         else (-2, -2), True)}

    # ---- overview ---------------------------------------------------------------------------
    def _show_view(self) -> None:
        self.query_one("#ov").display = self.view == "overview"
        self.query_one("#hgview").display = self.view == "hgs"
        self.query_one("#resv").display = self.view == "results"
        jobs = self.tab == "jobs"
        self.query_one("#overview").display = jobs
        self.query_one("#ovsteps").display = jobs
        self.query_one("#rtab").display = not jobs
        self._set_tabbar()
        first = "#overview" if jobs else "#rtab"
        self.query_one({"overview": first, "hgs": "#hgs", "results": "#res"}[self.view]).focus()
        if self.view == "overview":
            self._overview_footer() if jobs else self._rt_footer()
        self._update_help()                      # help follows view and tab

    def _set_tabbar(self) -> None:
        """`[Jobs] │ Results │ Setup`: the active tab bracketed and reversed."""
        names = (("jobs", "Jobs"), ("results", "Results"), ("setup", "Setup"))
        self._tab_text = " │ ".join(f"[{n}]" if k == self.tab else n for k, n in names)
        txt = Text()
        for i, (k, n) in enumerate(names):
            txt.append(" │ " if i else "")
            txt.append(f"[{n}]" if k == self.tab else n, style="reverse bold" if k == self.tab else "")
        txt.append("   tab: switch", style="dim")
        self.query_one("#tabbar", Static).update(txt)

    def _switch_tab(self, step: int = 1) -> None:
        """tab: Jobs -> Results -> Setup -> Jobs (shift+tab: the other way)."""
        for wid in ("#overview", "#rtab"):       # the new tab starts in row mode, the old one too
            t = self.query_one(wid, SortTable)
            if t.header:
                t.leave_header(to_row=False)
        nxt = TABS[(TABS.index(self.tab) + step) % len(TABS)]
        if nxt == "setup":
            self._open_setup()
            return
        self.tab = nxt
        self._show_view()
        self.refresh_bindings()                  # p shows on the Results tab only
        self._maybe_load_rtab()

    def _open_setup(self) -> None:
        from druid.setup_tui import SetupScreen
        self.tab = "setup"
        self._set_tabbar()
        self.push_screen(SetupScreen(), callback=self._setup_closed)

    def _setup_closed(self, to: "str | None" = None) -> None:
        """Back from Setup (esc on its list: Jobs; tab only moves inside it): druid.yaml is read
        again, so the edits made there take effect (and the species trees are re-read on the next Results load)."""
        try:                                     # both or neither: raw is written into run dirs
            raw = load_raw()
            cfg = core.load_config(paths.config_file())
        except (core.ConfigError, paths.NoProject, paths.OutsideProject) as e:
            self.notify(f"ERROR: {e} (the previous config is kept)", severity="error", markup=False)
        else:
            self.raw, self.cfg = raw, cfg
            self._universe = self._phyla = self._otree = None
            self._otree_err = ""
        self.tab = to if to in ("jobs", "results") else "jobs"
        self._show_view()
        self.refresh_bindings()
        self._maybe_load_rtab()
        self.load_bg()

    def action_focus_next(self) -> None:
        """tab: on the first screen it switches Jobs / Results / Setup; elsewhere it moves focus."""
        if self.view == "overview" and not isinstance(self.screen, ModalScreen):
            self._switch_tab()
            return
        super().action_focus_next()

    def action_focus_previous(self) -> None:
        if self.view == "overview" and not isinstance(self.screen, ModalScreen):
            self._switch_tab(-1)
            return
        super().action_focus_previous()

    # ---- Results tab --------------------------------------------------------------------------
    def _rt_loading(self) -> bool:
        return self.query_one("#rtab").has_class("loading")

    def _og_cache_check(self) -> None:
        """A POSSVM output finished (or vanished) since the cache was read: drop it.  On the
        Results tab the old rows stay shown while a background re-read runs; the cache is made
        unusable for the Results window at once."""
        if self._og_cache is None or _possvm_sig(self._ov_inputs[1]) == self._og_sig:
            return
        if self.view == "overview" and self.tab == "results":
            self._og_cache = dict(self._og_cache, hgs=frozenset())     # shown, not reusable
            self._reload_rtab(keep_rows=True)
        else:
            self._og_cache = None

    def _maybe_load_rtab(self) -> None:
        """Start the one read of every expected HG when the Results tab is shown and nothing is
        cached or loading; waits for the first refresh (no expected HGs known yet)."""
        if (self.view == "overview" and self.tab == "results" and self._og_cache is None
                and not self._rt_loading() and self._ov_inputs[0]):
            self._reload_rtab()

    def _reload_rtab(self, keep_rows: bool = False) -> None:
        """Start the one read.  keep_rows: the cached rows stay shown (greyed) until the new
        data land; the cache is already unusable for the Results window (hgs emptied)."""
        if not self._ov_inputs[0]:               # no snapshot yet: _apply -> _maybe_load_rtab reads
            return
        self._rt_gen += 1
        self._og_sig = _possvm_sig(self._ov_inputs[1])
        if not keep_rows:
            self._og_cache = None
        self.query_one("#rtab").add_class("loading")
        self._rt_note = "loading…"
        self._rt_footer()
        self._update_status()
        self._load_rtab(sorted(self._ov_inputs[0], key=model.hg_sort_key), self.rt_source,
                        self._rt_gen)

    @work(thread=True, exclusive=True, group="rtab")
    def _load_rtab(self, hgs: list, source: "str | None", gen: int) -> None:
        """Every expected HG's ortholog_groups.csv, read once (NFS; ~10 s for ~1,900 files).
        Own worker group: load_bg and the Results window load never cancel it, nor it them."""
        worker = get_current_worker()
        snap = dict(gen=gen, source=source or "possvm", rows=[], hgs=hgs, note="")
        try:
            snap["source"] = source or model.default_source(self.cfg)

            def progress(k: int, n: int) -> None:   # throttled: ~every 50 files
                if k and k % 50 == 0 and not worker.is_cancelled:
                    self.call_from_thread(self._rt_progress, gen, k, n)
            snap["rows"], _missing = model.group_ogs(
                self.cfg, hgs, snap["source"], progress=progress,
                cancelled=lambda: worker.is_cancelled or gen != self._rt_gen)
        except Exception as e:                   # never let a worker kill the app
            snap["note"] = f"cannot read {snap['source']}/: {e}"
        if worker.is_cancelled:
            return
        self.call_from_thread(self._apply_rtab, snap)

    def _rt_progress(self, gen: int, k: int, n: int) -> None:
        if gen == self._rt_gen and self._rt_loading():
            self._rt_note = f"loading {k}/{n}…"
            self._rt_footer()
            self._update_status()

    def _apply_rtab(self, snap: dict) -> None:
        if snap["gen"] != self._rt_gen:          # superseded by R or p
            self._update_status()                # (the spinner follows what is still awaited)
            return
        self.query_one("#rtab").remove_class("loading")
        self.rt_source = snap["source"]
        ok = not snap["note"]                    # a failed read caches nothing reusable
        self._og_cache = dict(source=snap["source"], rows={r.hg: r for r in snap["rows"]},
                              hgs=frozenset(snap["hgs"]) if ok else frozenset())
        self._rt_note = snap["note"]
        self._fill_rtab()
        self._update_status()

    def _fill_rtab(self) -> None:
        """Results tab rows: the Jobs groups, counted over the cached files (memory only)."""
        t = self.query_one("#rtab", SortTable)
        cache = self._og_cache or {}
        self.rt_rows = model.og_group_rows([r.group for r in self.ov_rows], self._ov_inputs[0],
                                           self.by, cache.get("rows", {}).values())
        self.rt_shown = rt_order(self.rt_rows, t.sort_state, self.rt_hide)
        keep, keep_row, col = self._key_at_cursor(t), t.cursor_row, t.cursor_column
        t.clear()
        for r in self.rt_shown:
            t.add_row(escape(r.group), str(r.hgs), str(r.with_output), str(r.ogs), str(r.genes),
                      str(r.zero), key=r.group)
        keys = [r.group for r in self.rt_shown]
        if keys:
            t.move_cursor(row=keys.index(keep) if keep in keys else max(0, min(keep_row, len(keys) - 1)),
                          column=col)
        t.border_title = " · ".join(
            ["Results"] + ([cache["source"]] if cache else [])
            + ([f"only {self.rt_hide} > 0"] if self.rt_hide else []))
        self._rt_footer()

    def _rt_footer(self) -> None:
        if self.view != "overview" or self.tab != "results":
            return
        key = self._key_at_cursor(self.query_one("#rtab", SortTable))
        r = next((x for x in self.rt_rows if x.group == key), None)
        lines = [self._rt_note] if self._rt_note else []
        if r is not None and self._og_cache is not None:
            line = (f"{r.group}: {r.hgs} HGs · {r.with_output} with output · {r.ogs} OGs · "
                    f"{r.genes} genes · {r.zero} OGs with support 0")
            bad = r.unreadable                   # the group's own count
            if bad:
                line += f" · {bad} HG{'' if bad == 1 else 's'} unreadable"
            lines.append(line)
        self._rt_foot = "\n".join(lines)         # status only: the keys are in the strip's help
        self.query_one("#ovfoot", Static).update(escape(self._rt_foot))

    def _fill_overview(self, rows: list) -> None:
        self.ov_rows = rows                      # as computed; ov_shown is what the table shows
        self.ov_shown = ov_order(rows, self.ov_sort, self.ov_hide)
        t =self.query_one("#overview", DataTable)
        keep = self._key_at_cursor(t)
        keep_row = t.cursor_row
        col = t.cursor_column
        if col >= 2 and stage_at_column(col) is None:      # never restore onto the separator
            col += 1
        t.clear()
        width = {st: max((len(f"{c[0]}/{sum(c)}") for r in self.ov_shown
                          for c in [r.per_stage.get(st)] if c), default=0)
                 for st in OV_COLUMNS if st is not None}     # numbers right-aligned per column
        for r in self.ov_shown:
            cells = []
            for st in OV_COLUMNS:
                if st is None:
                    cells.append(OV_SEP)
                    continue
                c = r.per_stage.get(st)
                if c is None:
                    cells.append("n/a")
                    continue
                cells.append(ov_cell(c, width[st], self.OV_BAR, self.OV_GLYPHS))
            t.add_row(r.group, str(r.total), *cells, key=r.group)
        keys = [r.group for r in self.ov_shown]
        t.move_cursor(row=keys.index(keep) if keep in keys else max(0, min(keep_row, len(keys) - 1)),
                      column=col)
        t.border_title = self._ov_title()
        self.call_after_refresh(self._fill_ovsteps)   # column widths settle on the next refresh
        self._overview_footer()
        if self._og_cache is not None:          # same groups (c / f, refresh) on the Results tab
            self._fill_rtab()

    def _fill_ovsteps(self) -> None:
        """The line above the overview: "step 1 ──┐" over search..cluster (the ┐ on the │
        separator), "step 2 ──" over align..possvm; widths from the rendered columns."""
        t = self.query_one("#overview", SortTable)
        w = [c.get_render_width(t) for c in t.ordered_columns]
        a, sep, b = ov_column(core.FAMILY_STAGES[0]), ov_column(core.FAMILY_STAGES[-1]) + 1, \
            ov_column(core.HG_STAGES[0])
        if len(w) < b + 1:
            return
        w1, ws, w2 = sum(w[a:sep]), w[sep], sum(w[b:])
        pad = t.cell_padding
        line = (" " * (1 + sum(w[:a]))                               # 1: the table's border
                + ("step 1 " + "─" * w1)[:w1]
                + "─" * pad + "┐" + " " * max(ws - pad - 1, 0)
                + ("step 2 " + "─" * w2)[:w2])
        sx = int(t.scroll_x)                                         # follow a horizontal scroll
        self._ovsteps_text = line[:1] + line[1 + sx:]
        self.query_one("#ovsteps", Static).update(Text(self._ovsteps_text, no_wrap=True))  # keeps the indent

    def _ov_title(self) -> str:
        parts = ["Overview"]
        if self.ov_sort is not None:
            col, rev = self.ov_sort                # the same arrow as the column header
            parts.append(f"sort: {col} {sort_arrow(col != 'group', rev)}")
        if self.ov_hide is not None:
            parts.append(f"only actionable at {self.ov_hide}")
        return " · ".join(parts)

    def _ov_column(self) -> "str | None":
        """What the highlighted overview column sorts by: "group", "HGs", a stage name, or None
        on the │ separator. Stage columns go through stage_at_column (step1's one mapping)."""
        t = self.query_one("#overview", DataTable)
        if not t.columns:
            return None
        col = t.cursor_column
        return ("group", "HGs")[col] if col < 2 else stage_at_column(col)

    def _overview_footer(self) -> None:
        if self.tab != "jobs":                   # #ovfoot belongs to the Results tab then
            return
        key = self._key_at_cursor(self.query_one("#overview", DataTable))
        r = next((x for x in self.ov_rows if x.group == key), None)
        if r is None:
            return
        parts = [f"{st} {c[0]}/{c[1]}/{c[2]}/{c[3]}" for st, c in r.per_stage.items() if c]
        self.query_one("#ovfoot", Static).update(
            f"[b]{escape(r.group)}[/] {r.total} HGs · {r.n_fams} families · "
            "done/running/ready/blocked: " + " · ".join(parts))

    def _regroup(self) -> None:
        exp, states, fams, fstates = self._ov_inputs
        rows, _k = model.group_rows(self.cfg, exp, self.by, states=states,   # in-memory only
                                    fams=fams, fstates=fstates)
        self._fill_overview(rows)
        if self.view == "hgs":
            self._fill_stages()

    def _fill_stages(self) -> None:
        """Stages panel = the counts of the group being viewed (ALL when none), taken from the
        overview rows so the panel and the group-restricted HG list agree."""
        row = next((r for r in self.ov_rows if r.group == (self.group or "ALL")), None)
        if row is None and self.ov_rows:
            row = self.ov_rows[0]
        if row is None:
            return
        st = self.query_one("#stages", DataTable)
        keep_stage = self.stage
        st.clear()
        for name in TUI_STAGES:
            c = row.per_stage.get(name)
            if c is None:
                st.add_row(name, "n/a", "", "", "", "", key=name)
            else:
                total = row.n_fams if name in core.FAMILY_STAGES else row.total   # families / HGs
                st.add_row(name, str(c[0]), str(c[1]), str(c[2]), str(c[3]), str(total), key=name)
        if keep_stage in TUI_STAGES:
            st.move_cursor(row=TUI_STAGES.index(keep_stage))

    def _auto_pick_filter(self) -> None:
        """While the filter is still the automatic one, pick the first filter (FILTERS order)
        that shows something for this group and stage; "actionable" if none does.  Waits for real
        data (by_stage) and is done once it has chosen from it."""
        if not self._auto_filter or not self.by_stage:
            return
        self._auto_filter = False
        for f in FILTERS:
            self.filter = f
            if self.visible():
                return
        self.filter = FILTERS[0]

    def open_group(self, name: str, stage: "str | None" = None) -> None:
        self.group = None if name == "ALL" else name
        self.view = "hgs"
        self.filter = FILTERS[0]
        self.selected.clear()
        if stage is not None and core.applicable(self.cfg, stage):
            self.stage = stage
            st = self.query_one("#stages", DataTable)
            if st.row_count:
                st.move_cursor(row=TUI_STAGES.index(stage))
        self.rows = self.by_stage.get(self.stage, [])
        self._auto_filter = True
        self._auto_pick_filter()
        self._hist_loading = not self.by_stage
        self._show_view()
        self.query_one("#stages").focus()        # opening: pane 1 is active (Grygoriy, 02/11/2026)
        self.query_one("#hgview").set_class(not self.by_stage, "loading")   # grey until data
        self._fill_stages()
        self._fill_hgs(keep="")
        self.load_bg()

    def check_action(self, action: str, parameters: tuple) -> "bool | None":
        """Footer shows only the keys of the current view."""
        if action != "quit" and (isinstance(self.screen, (tv_widget.TreeScreen, KeysScreen))
                                 or type(self.screen).__name__ == "SetupScreen"):
            return False                     # the tree / key list / Setup owns the keys; ctrl+q
            #                                  (Textual's quit; plain q is never bound) still quits
        f = self.focused
        if action in ("toggle", "select_all", "resubmit", "log", "open_results", "open_tree") \
                and isinstance(f, SortTable) and f.header:
            return False                         # header mode: the hidden row-0 cursor is not a target
        if action == "open_tree":
            return self.view == "results" or (self.view == "overview" and self.tab == "results")
        if action == "run_step1":                # Jobs tab only, never from inside a dialog
            return (self.view == "overview" and self.tab == "jobs"
                    and self.screen is self.screen_stack[0])
        if action in ("by_category", "sort", "hide"):
            return self.view == "overview"
        if action in ("toggle", "select_all", "unselect_all", "resubmit", "log"):
            return self.view == "hgs"
        if action == "back":
            return self.view in ("hgs", "results")
        if action in ("open_results", "cycle_filter"):
            return self.view in ("overview", "hgs")
        if action == "toggle_source":
            return self.view == "results" or (self.view == "overview" and self.tab == "results")
        if action == "member_filter":
            return self.view == "results"
        return True

    def action_back(self) -> None:
        if self.view == "results":
            inp = self.query_one("#memfilter", Input)
            pane = self._flt_pane if inp.display else self._focused_pane()
            # esc in the box clears that pane's filter; esc outside the box clears EVERY pane's
            # filter if any is set; only an esc with no filter left leaves Results (Grygoriy)
            if inp.display or any(self._flt.values()):
                panes = [pane] if inp.display else [p for p, q in self._flt.items() if q]
                inp.value = ""
                inp.display = False
                for p in panes:
                    self._flt[p] = ""
                    self._refilter(p)
                self.query_one(self._PANE_ID[pane]).focus()
                return
            self._res_gen += 1                   # a load still running is dropped when it lands
            self._tree_gen += 1                  # ... and so is a tree still loading
            self.workers.cancel_group(self, "results")   # ... and stops reading files
            self.view = self.res_from
            self._show_view()
            self.load_bg()                       # the refresh skipped the HG history meanwhile
        elif self.view == "hgs":
            self.view = "overview"
            self._show_view()

    def action_by_category(self) -> None:
        if self.view == "overview":
            self.by = "category"
            self._regroup()

    @property
    def ov_sort(self) -> "tuple | None":
        """The overview's sort = its table's header sort: one state for s and the header."""
        return self.query_one("#overview", SortTable).sort_state

    def action_sort(self) -> None:
        """s with the first-screen table not focused (focused, the table's own s handles it)."""
        if self.view == "overview":
            t = self.query_one("#overview" if self.tab == "jobs" else "#rtab", SortTable)
            t.sort_by(t.cursor_column)           # no-op on the │ separator

    def _resorted(self, t: "SortTable") -> None:
        """A table's sort changed (header enter / s, or s on a cell): reorder it in memory."""
        if t.id == "overview":
            self._fill_overview(self.ov_rows)
        elif t.id == "rtab":
            self._fill_rtab()
        elif t.id == "hgs":
            self._fill_hgs(keep=self._key_at_cursor(t))   # the cursor stays on the same HG
        elif t.id == "res":
            self._fill_res(self._key_at_cursor(t))
        elif t.id == "ogs":
            self._fill_ogs(keep=self._key_at_cursor(t))
        elif t.id == "members":
            self._fill_members()

    def action_hide(self) -> None:
        if self.view == "overview" and self.tab == "results":
            t = self.query_one("#rtab", SortTable)
            name = t.cols[t.cursor_column].name if t.cols else None
            if name in (None, "group"):
                self.notify("h: move to a count column first", severity="warning")
                return
            self.rt_hide = None if self.rt_hide == name else name
            self._fill_rtab()                    # in memory only
            return
        col = self._ov_column() if self.view == "overview" else None
        if col in (None, "group", "HGs"):        # not a stage column (incl. the │ separator)
            self.notify("h: move to a stage column first", severity="warning")
            return
        self.ov_hide = None if self.ov_hide == col else col
        self._fill_overview(self.ov_rows)        # in memory only

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        if self.view == "overview" and event.data_table.id == "rtab":
            self._open_results(event.cell_key.row_key.value, self.by, source=self.rt_source)
            return
        if event.data_table.id != "overview" or self.view != "overview":
            return
        stage = stage_at_column(event.coordinate.column)   # None: group, HGs or │ -> current stage
        self.open_group(event.cell_key.row_key.value, stage)

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        if event.data_table.id == "overview":
            self._overview_footer()
        elif event.data_table.id == "rtab":
            self._rt_footer()

    def _fill_hgs(self, keep: "str | None" = None) -> None:
        """Rebuild the HG table, keeping the cursor on the same HG (clear() resets it to row 0).
        `keep` overrides which HG to stay on (default: the one under the cursor now)."""
        keep = keep if keep is not None else self._cursor_hg()
        self._set_units()
        t = self.query_one("#hgs", DataTable)
        t.clear()
        fam_stage = self.stage in core.FAMILY_STAGES
        for r in self.visible():
            n = f"{self.hg_count.get(r.hg, 0)} HGs" if fam_stage else str(self.nseq.get(r.hg, 0))
            a = r.last
            t.add_row("●" if r.hg in self.selected else " ", r.hg, n,
                      f"[{STATE_STYLE[r.state]}]{r.state}[/]",
                      model.bump_reason(a) if a else "–",
                      f"{a.mem}/{a.time}" if a else "–",
                      f"{a.peak_rss}/{a.realtime}" if a else "–", key=r.hg)
        vis = self.visible()
        if vis:
            idx = next((i for i, r in enumerate(vis) if r.hg == keep), 0)
            t.move_cursor(row=idx)
        self._show_detail()

    def _cursor_hg(self) -> "str | None":
        t = self.query_one("#hgs", DataTable)
        vis = self.visible()
        return vis[t.cursor_row].hg if vis and 0 <= t.cursor_row < len(vis) else None

    def _detail_text(self, hg: str) -> str:
        """Detail panel for `hg`: an HG (six HG stages), or a family on search / cluster."""
        if self.stage in core.FAMILY_STAGES:
            head, stages = f"[b]{hg}[/]  {self.hg_count.get(hg, 0)} HGs", core.FAMILY_STAGES
        else:
            head, stages = f"[b]{hg}[/]  {self.nseq.get(hg, 0)} seqs", core.HG_STAGES
        latest = history.latest_by_stage([a for a in self.atts if a.hg == hg])
        lines = [head, ""]
        for st in stages:
            rs = next((r for r in self.by_stage.get(st, []) if r.hg == hg), None)
            s_ = rs.state if rs else "n/a"
            a = latest.get(st)
            extra = (f"  {a.status} ({history.reason(a.status, a.exit)})  req {a.cpus}/{a.mem}/{a.time}"
                     f"  used {a.peak_rss}/{a.realtime}" if a else "")
            lines.append(f"{st:<12} [{STATE_STYLE.get(s_, 'white')}]{s_:<8}[/]{extra}")
        a = latest.get(self.stage)
        if a is not None:
            lines += ["", f"log: {a.log}"]
        return "\n".join(lines)

    def _show_detail(self) -> None:
        hg = self._cursor_hg()
        self.query_one("#detail", Static).update("" if hg is None else self._detail_text(hg))

    # ---- events / actions -------------------------------------------------------------------
    @staticmethod
    def _key_at_cursor(t: DataTable) -> "str | None":
        if not t.row_count or not 0 <= t.cursor_row < t.row_count:
            return None
        return t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        t = event.data_table
        # A refill (clear + add_row) posts highlights for row 0 that arrive after the cursor
        # was restored; only act on a highlight that is still where the cursor is.
        if event.row_key is None or event.row_key.value != self._key_at_cursor(t):
            return
        if t.id == "stages" and event.row_key.value in core.STAGES:
            if event.row_key.value != self.stage:
                self.stage = event.row_key.value
                self.selected.clear()
                self.rows = self.by_stage.get(self.stage, [])
                self._auto_filter = True         # a new stage picks its filter again, actionable
                self._auto_pick_filter()         # first (Grygoriy, 02/11/2026)
                self._fill_hgs(keep="")
        elif t.id == "hgs":
            self._show_detail()
        elif t.id == "res":
            self._fill_ogs()
        elif t.id == "ogs":
            self._show_og()

    def action_cycle_filter(self) -> None:
        if self.view == "results":           # f has no meaning in Results (check_action hides it)
            return
        if self.view == "overview":
            self.by = "family"
            self._regroup()
            return
        self._auto_filter = False
        self.filter = FILTERS[(FILTERS.index(self.filter) + 1) % len(FILTERS)]
        self._fill_hgs()

    def _in_hgs_pane(self) -> bool:
        """Selection keys act on the HG list only; elsewhere they warn and do nothing."""
        if self.focused is not None and self.focused.id == "hgs":
            return True
        self.notify("tab to 2 HGs to select", severity="warning")
        return False

    def action_toggle(self) -> None:
        if not self._in_hgs_pane():
            return
        hg = self._cursor_hg()
        if hg:
            self.selected ^= {hg}
            self._fill_hgs()

    def action_select_all(self) -> None:
        if not self._in_hgs_pane():
            return
        self.selected = {r.hg for r in self.visible()}
        self._fill_hgs()

    def action_unselect_all(self) -> None:
        if not self._in_hgs_pane():
            return
        self.selected -= {r.hg for r in self.visible()}
        self._fill_hgs()

    def action_refresh(self) -> None:
        self._og_cache = None                    # R re-reads the ortholog-group files too
        self._rt_gen += 1                        # a tab read still in flight must not cache pre-R data
        self.workers.cancel_group(self, "rtab")
        self.query_one("#rtab").remove_class("loading")
        if self.view == "overview" and self.tab == "results":
            self._reload_rtab()
        self._update_status()                    # the dropped read no longer holds the spinner
        if self.view == "results" and self.res_source is not None:
            self._reload_results()          # keeps group / source / cursor where possible
        self.load_bg()

    def action_resubmit(self) -> None:
        if not self._in_hgs_pane():
            return
        rows = [r for r in self.rows if r.hg in self.selected]
        if not rows:
            self.notify("nothing selected (space / a)", severity="warning")
            return
        groups = resource_groups(self.cfg, self.stage, rows, self.nseq)
        self.push_screen(ResubmitScreen(self.cfg, self.stage, groups, self.raw),
                         lambda _jids: (self.selected.clear(), self.load_bg()))

    def action_run_step1(self) -> None:
        """S: step 1 (search → cluster) in the run box; the Jobs tab reloads when it closes."""
        self.push_screen(RunScreen(self.cfg, self.raw), lambda _jids: self.load_bg())

    def action_log(self) -> None:
        hg = self._cursor_hg()
        a = next((r.last for r in self.rows if r.hg == hg), None) if hg else None
        if a is None:
            self.notify("no attempt recorded for this HG at this stage", severity="warning")
            return
        self.push_screen(LogScreen(a.log))

    # ---- Results window ---------------------------------------------------------------------
    def action_open_results(self) -> None:
        if self.view == "overview" and self.tab == "results":
            group = self._key_at_cursor(self.query_one("#rtab", DataTable))
            if group is not None:
                self._open_results(group, self.by, source=self.rt_source)
        elif self.view == "overview":
            group = self._key_at_cursor(self.query_one("#overview", DataTable))
            if group is not None:
                self._open_results(group, self.by)
        elif self.view == "hgs":
            hg = self._cursor_hg()
            if hg is None:
                self.notify("nothing under the cursor", severity="warning")
                return
            if self.stage in core.FAMILY_STAGES:   # a family row (search / cluster): its HGs
                self._open_results(hg, "family")
            else:
                self._open_results(model.group_key(hg, self.by), self.by, focus=hg)

    def _open_results(self, group: str, by: str, focus: "str | None" = None,
                      source: "str | None" = None) -> None:
        """Results window for a group of HGs: `group` under grouping `by` (ALL = every HG; a
        family id under "family" = that family's HGs).  The HG list comes from the last
        snapshot in memory (_ov_inputs[0] = expected HGs); the files are read by _load_results."""
        exp = self._ov_inputs[0]
        self.res_hgs = sorted((h for h in exp if group == "ALL" or model.group_key(h, by) == group),
                              key=model.hg_sort_key)
        self.res_from, self.res_group, self._res_focus = self.view, group, focus
        self.res_source, self.res_rows, self.res_missing = None, [], 0
        self._res_want = source                 # None = default_source(), in the worker
        self._flt = {"res": "", "ogs": "", "members": ""}
        inp = self.query_one("#memfilter", Input)
        inp.value = ""
        inp.display = False
        self.query_one("#res", DataTable).clear()
        self._set_res_title()
        self.view = "results"
        self._show_view()
        self._reload_results()

    def _reload_results(self) -> None:
        """Grey the window and start a load; the #res rows stay (greyed) so the cursor's HG is
        kept across `p`, while the other panes empty until the new source is read."""
        self._res_gen += 1
        self.res_rows = []
        self.query_one("#resv").add_class("loading")
        self._res_note = "loading…"
        self.sub_title = f"Results · {self.res_group} · {self.res_source or '…'}"
        self._fill_ogs()
        self._load_results(list(self.res_hgs), self.res_source or self._res_want, self._res_gen,
                           self._og_cache)

    @work(thread=True, exclusive=True, group="results")
    def _load_results(self, hgs: list, source: "str | None", gen: int,
                      cache: "dict | None" = None) -> None:
        """Reads the ortholog_groups.csv files (NFS) and, until they have been read once, the
        species tree tips and species_info.tsv: never on the UI thread.  Own worker group:
        load_bg (default group, exclusive) must not cancel it, nor it load_bg."""
        worker = get_current_worker()
        snap = dict(gen=gen, source=source or "possvm", rows=[], missing=0, note="",
                    universe=self._universe, phyla=self._phyla, sp_note="",
                    otree=self._otree, origins={}, otree_err="")
        try:
            snap["source"] = source or model.default_source(self.cfg)
            def progress(k: int, n: int) -> None:   # throttled: ~every 50 files
                if k and k % 50 == 0 and not worker.is_cancelled:
                    self.call_from_thread(self._res_progress, gen, k, n)
            if (cache is not None and cache["source"] == snap["source"]
                    and set(hgs) <= cache["hgs"]):   # the Results tab read them: no 2nd read
                snap["rows"] = [cache["rows"][h] for h in hgs if h in cache["rows"]]
                snap["missing"] = len(hgs) - len(snap["rows"])
            else:
                snap["rows"], snap["missing"] = model.group_ogs(
                    self.cfg, hgs, snap["source"], progress=progress,
                    cancelled=lambda: worker.is_cancelled or gen != self._res_gen)
        except Exception as e:                   # never let a worker kill the app
            snap["note"] = f"cannot read {snap['source']}/: {e}"
        notes = []
        if snap["universe"] is None:
            try:
                snap["universe"] = model.species_universe(self.cfg)
            except Exception as e:
                notes.append(f"species tree {self.cfg.params.get('SPECIES_TREE', '')}: {e}")
        if snap["phyla"] is None:
            try:
                snap["phyla"] = model.phyla(self.cfg)
            except Exception as e:
                notes.append(f"{model.species_info_path(self.cfg)}: {e} (phyla shown as unknown)")
        if snap["otree"] is None and self._origins_on():      # params.origins off: never read
            try:
                snap["otree"] = model.origin_tree(self.cfg)
            except Exception as e:
                snap["otree_err"] = f"origin tree {model.origin_tree_path(self.cfg)}: {e}"
        if snap["otree"] is not None and self._origins_on():
            snap["origins"] = model.og_origins(snap["rows"], snap["otree"])
        snap["sp_note"] = "; ".join(notes)
        if worker.is_cancelled:
            return
        self.call_from_thread(self._apply_results, snap)

    def _res_progress(self, gen: int, k: int, n: int) -> None:
        if gen == self._res_gen and self.query_one("#resv").has_class("loading"):
            self._res_note = f"loading {k}/{n}…"
            self._results_footer()

    def _apply_results(self, snap: dict) -> None:
        if snap["gen"] != self._res_gen:         # superseded: esc, another o, or p meanwhile
            self._update_status()
            return
        self.sub_title = f"Results · {self.res_group} · {snap['source']}"
        self.query_one("#resv").remove_class("loading")
        self.res_source, self.res_rows, self.res_missing = snap["source"], snap["rows"], snap["missing"]
        self._universe, self._phyla, self._sp_note = snap["universe"], snap["phyla"], snap["sp_note"]
        self._otree, self._origins = snap["otree"], snap["origins"]
        if snap["otree_err"]:
            self._notify_once(snap["otree_err"])
        self._res_note = snap["note"] or ("" if self.res_rows else
                                          f"no ortholog groups yet ({self.res_source} not done)")
        t = self.query_one("#res", DataTable)
        focus, self._res_focus = self._res_focus, None
        keep = focus or self._key_at_cursor(t)
        if focus and focus not in {r.hg for r in self.res_rows}:
            self.notify(f"{focus}: no output in {self.res_source}", severity="warning")
            keep = None
        self._fill_res(keep)
        self._fill_ogs()

    def _fill_res(self, keep: "str | None") -> None:
        """Results table: the loaded HGs whose id contains the `/` filter (in memory)."""
        t = self.query_one("#res", DataTable)
        if self.query_one("#resv").has_class("loading"):
            # rows not read yet (res_rows is []): redrawing now would empty the table and lose
            # the cursor's HG; the filter / sort apply when _apply_results lands
            self._set_res_title()
            return
        q = self._flt["res"].lower()
        rows = sort_rows([r for r in self.res_rows if q in r.hg.lower()], t.sort_state, RES_KEYS)
        t.clear()
        for r in rows:
            if r.error:
                t.add_row(r.hg, "–", "–", "!", key=r.hg)
            else:
                t.add_row(r.hg, str(len(r.ogs)), str(sum(len(o.genes) for o in r.ogs)),
                          str(sum(1 for o in r.ogs if o.support == 0)), key=r.hg)
        keys = [r.hg for r in rows]
        if keys:
            t.move_cursor(row=keys.index(keep) if keep in keys else 0)
        self._set_res_title()

    def _ftag(self, pane: str) -> str:
        return f" · /{self._flt[pane]}" if self._flt[pane] else ""

    def _set_res_title(self) -> None:
        self.query_one("#res").border_title = f"Results · {self.res_group}{self._ftag('res')}"

    _PANE_ID = {"res": "#res", "ogs": "#ogs", "members": "#members"}
    _PANE_NAME = {"res": "Results", "ogs": "OGs", "members": "members"}

    def _focused_pane(self) -> str:
        f = self.focused
        return {"res": "res", "ogs": "ogs"}.get(getattr(f, "id", None), "members")

    def _refilter(self, pane: str) -> None:
        """Redraw `pane` after its filter changed and re-point the panes to its right (memory)."""
        if pane == "res":
            self._fill_res(self._key_at_cursor(self.query_one("#res", DataTable)))
            self._fill_ogs()
        elif pane == "ogs":
            self._fill_ogs()
        else:
            self._fill_members()
            self._results_footer()

    def action_open_tree(self) -> None:
        """t in Results: the HG's gene tree in treeview (vendored), from the current p source.
        Cursor in #res -> the root; #ogs -> the OG's MRCA, its members highlighted; #members ->
        that member's tip.  esc in the tree comes back here unchanged."""
        if self.view == "overview" and self.tab == "results":
            self.notify("open a group's Results (o), then t", severity="warning")
            return
        if self.view != "results" or self.res_source is None:
            return
        r = self._cur_res()
        if r is None:
            self.notify("no HG under the cursor", severity="warning")
            return
        pane = getattr(self.focused, "id", None) or "res"
        og = self._cur_og() if pane == "ogs" else None
        gene = None
        if pane == "members":
            key = self._key_at_cursor(self.query_one("#members", DataTable))
            gene = key.split(":", 1)[1] if key else None
        self._tree_gen += 1                      # an earlier, slower load is dropped when it lands
        self._load_tree(r.hg, self.res_source, og, gene, self._tree_gen)

    def _tree_current(self, gen: int) -> bool:
        """A load's result may still be shown: it is the latest t, Results is still open, and no
        tree is on top already."""
        return (gen == self._tree_gen and self.view == "results"
                and type(self.screen).__name__ != "TreeScreen")

    def _tree_warn(self, gen: int, msg: str) -> None:
        if self._tree_current(gen):
            self.notify(msg, severity="warning")

    @work(thread=True, exclusive=True, group="tree")
    def _load_tree(self, hg: str, source: str, og, gene: "str | None", gen: int) -> None:
        """Reads the newick, its ortholog_groups.csv (as metadata) and species_info.tsv (colours)
        off the UI thread.  Any failure is a warning; the TUI never crashes on a bad tree."""
        notes = []
        try:
            from treeview import model as tvm      # vendored: core puts phylocli/vendor on sys.path
            files = model.hg_tree_files(self.cfg, hg, source)
            if files is None:
                raise FileNotFoundError(f"{hg}: no {source} output")
            path, csv = files
            if not path.is_file():
                raise FileNotFoundError(f"{hg}: no tree {path.name} in {source}/")
            tree = tvm.load(path)
            try:
                cols, meta = tvm.load_meta(csv)
            except (OSError, ValueError) as e:
                cols, meta = None, None
                notes.append(f"{csv.name}: {e} (no metadata)")
            try:
                colours = tvm.load_colours(model.species_info_path(self.cfg))
            except Exception:                  # colours are cosmetic: species hash colours
                colours = {}
            m = tvm.TreeModel(tree, sep="_", colours=colours, meta=meta, meta_cols=cols)
        except Exception as e:                 # missing file, bad newick, ...
            self.call_from_thread(self._tree_warn, gen, f"tree: {e}")
            return
        focus, hl, title = 0, [], f"{hg} · {source}"
        if og is not None:
            ids = [m.tip(g.gene) for g in og.genes]
            hl = [i for i in ids if i is not None]
            if len(hl) < len(ids):
                notes.append(f"{len(ids) - len(hl)} of {len(ids)} members not in the tree")
            focus = m.mrca(hl)
            title += f" · {og.id}"
        if gene is not None:
            i = m.tip(gene)
            if i is None:
                notes.append(f"{gene} not in the tree")
            else:
                focus = i
            title += f" · {gene}"
        self.call_from_thread(self._push_tree, gen, m, focus, hl, title, path, notes)

    def _push_tree(self, gen: int, m, focus: int, hl: list, title: str, path, notes: list) -> None:
        if not self._tree_current(gen):
            return
        self.push_screen(DruidTreeScreen(m, title=title, path=path, focus=focus, highlight=hl,
                                         write_guard=paths.writable))
        for n in notes:
            self.notify(n, severity="warning")

    def _cur_res(self):
        key = self._key_at_cursor(self.query_one("#res", DataTable))
        return next((r for r in self.res_rows if r.hg == key), None)

    def _cur_og(self):
        r = self._cur_res()
        if r is None:
            return None
        key = self._key_at_cursor(self.query_one("#ogs", DataTable))
        return next((o for o in r.ogs if o.id == key), None)

    def _origins_on(self) -> bool:
        """params.origins (default on): off, ORIGIN_TREE is never read and no origin is shown."""
        return bool(self.cfg.params.get("origins", True))

    def _origin_text(self, og_id: str) -> str:
        """`?` while the origin tree is unreadable, `–` for an OG with no species on it."""
        if self._otree is None:
            return "?"
        o = self._origins.get(og_id)
        return "–" if o is None else o.label

    def _fill_ogs(self, keep: "str | None" = None) -> None:
        """OG table of the HG under the Results cursor (in memory), then its members/species.
        The cursor stays on OG `keep` (default: the OG under the cursor now) when it is still
        shown, e.g. while typing an OGs or Results filter or after a re-sort; else row 0."""
        r = self._cur_res()
        t = self.query_one("#ogs", SortTable)
        if keep is None:
            keep = self._key_at_cursor(t)
        on = self._origins_on()
        cols = OG_COLS if on else [c for c in OG_COLS if c.name != "origin"]
        if t.cols != cols:                       # params.origins changed in Setup
            if not on and t.sort_state is not None and t.sort_state[0] == "origin":
                t.sort_state = None
            t.set_cols(cols)
        t.clear()
        t.border_title = f"OGs · {r.hg if r else '–'} · {self.res_source or '…'}{self._ftag('ogs')}"
        q = self._flt["ogs"].lower()
        ogs = [o for o in r.ogs if q in o.id.lower() or q in o.name.lower()
               or (on and q in self._origin_text(o.id).lower())] if r else []
        keys = dict(OG_KEYS, origin=(lambda o: _origin_key(self._origins.get(o.id)), False))
        if t.sort_state is not None and t.sort_state[0] == "origin":
            placed = [o for o in ogs if self._origins.get(o.id) is not None]
            ogs = (sort_rows(placed, t.sort_state, keys)
                   + [o for o in ogs if self._origins.get(o.id) is None])
        else:
            ogs = sort_rows(ogs, t.sort_state, keys)
        for og in ogs:
            sup = ("–" if og.support is None else "0.0 ⚠" if og.support == 0
                   else f"{og.support:.1f}")
            cells = [_short_og(og.id), str(len(og.genes)), str(len({m.species for m in og.genes})),
                     sup, escape(_trunc(og.name))]
            if on:
                cells.append(escape(self._origin_text(og.id)))
            t.add_row(*cells, key=og.id)
        keys = [o.id for o in ogs]
        if keys:
            t.move_cursor(row=keys.index(keep) if keep in keys else 0)
        self._show_og()

    def _show_og(self) -> None:
        """members + species panes for the OG under the OGs cursor (in memory, no file access)."""
        r, og = self._cur_res(), self._cur_og()
        self.query_one("#members").border_title = (
            (f"members · {_short_og(og.id)} {escape(og.name)}" if og else "members")
            + self._ftag("members"))
        origin = f" · origin {self._origin_text(og.id)}" if og and self._origins_on() else ""
        self.query_one("#species_box").border_title = (
            f"species · {_short_og(og.id)}{origin}" if og else "species")
        self._fill_members()
        if r is not None and r.error:
            text = r.error
        elif og is None:
            text = self._res_note
        else:
            uni = self._universe or []
            w = self.query_one("#species_box").size.width - 4      # 0 while hidden: default
            lines = species_lines(model.og_species_stats(og, uni, self._phyla or {}),
                                  model.og_outside(og, uni), **({"width": w} if w > 20 else {}))
            text = "\n".join(([self._sp_note, ""] if self._sp_note else []) + lines)
        self._species_text = text
        self.query_one("#species", Static).update(species_text(text))   # coverage colours
        self._results_footer()

    def _fill_members(self) -> None:
        """Annotation rows of the highlighted OG, filtered by the `/` box (case-insensitive
        substring on any column)."""
        og = self._cur_og()
        t = self.query_one("#members", SortTable)
        t.clear()
        q = self._flt["members"].lower()
        self.query_one("#members").border_title = (
            (f"members · {_short_og(og.id)} {escape(og.name)}" if og else "members")
            + self._ftag("members"))
        for i, m in sort_rows(list(enumerate(og.genes if og else [])), t.sort_state, MEM_KEYS):
            cells = (m.gene, m.species, m.ref, m.ref_support)
            if q and not any(q in c.lower() for c in cells):
                continue
            shown = (m.gene, m.species, _trunc(m.ref), _trunc(m.ref_support, 12))
            t.add_row(*(escape(c) for c in shown), key=f"{i}:{m.gene}")

    def _results_footer(self) -> None:
        r = self._cur_res()
        head = r.error if r is not None and r.error else self._res_note
        empty = {"res": self.query_one("#res", DataTable).row_count == 0 and bool(self.res_rows),
                 "ogs": self.query_one("#ogs", DataTable).row_count == 0 and r is not None
                        and not r.error and bool(r.ogs),
                 "members": self.query_one("#members", DataTable).row_count == 0
                            and self._cur_og() is not None}
        nm = [f"no match: {self._PANE_NAME[p]} /{self._flt[p]}" for p in empty
              if empty[p] and self._flt[p]]
        if nm:
            head = "; ".join(([head] if head else []) + nm)
        hint = "⚠ = support 0 (GeneRax bug case" + ("; check possvm_prev)" if self.res_source == "possvm" else ")")
        parts = ([f"{len(r.ogs)} OGs"] if r is not None and not r.error else []) + [
            self.res_source or "…", hint]
        if self.res_missing:
            parts.append(f"{self.res_missing} HG{'' if self.res_missing == 1 else 's'} without output")
        lines = ([head] if head else []) + [
            " · ".join(parts)]
        self._res_foot = "\n".join(lines)
        self.query_one("#resfoot", Static).update(escape(self._res_foot))
        self._update_status()

    def action_toggle_source(self) -> None:
        if self.view == "overview" and self.tab == "results":
            if self._og_cache is None:           # the first read is still running
                return
            self.rt_source = "possvm_prev" if self._og_cache["source"] == "possvm" else "possvm"
            self._reload_rtab()
            return
        if self.view != "results" or self.res_source is None:   # first load still running
            return
        self.res_source = "possvm_prev" if self.res_source == "possvm" else "possvm"
        self._reload_results()

    def action_member_filter(self) -> None:
        if self.view != "results":
            return
        pane = self._focused_pane()
        inp = self.query_one("#memfilter", Input)
        self._flt_pane = pane
        inp.placeholder = f"filter {self._PANE_NAME[pane]}: (enter: keep · esc: clear)"
        inp.border_title = f"filter {self._PANE_NAME[pane]}"
        inp.value = self._flt[pane]
        inp.display = True
        inp.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "memfilter":        # (the resubmit dialog's Inputs have other ids)
            pane = self._flt_pane
            if event.value != self._flt[pane]:
                self._flt[pane] = event.value
                self._refilter(pane)
                if pane != "members":            # the other panes' titles follow the new filter
                    self._set_res_title()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "memfilter":        # enter: keep the filter, back to the pane
            event.input.display = False
            self.query_one(self._PANE_ID[self._flt_pane]).focus()


def resource_groups(cfg: core.Config, stage: str, rows: list, nseq: "dict | None" = None) -> list:
    """[(reason, bumped Res, hgs)] for the selected rows, one entry per distinct pair.
    `nseq` ({hg: n sequences}) spares `core.resources` the FASTA read (UI thread)."""
    table = core.load_resources_tsv(Path(cfg.params["resources_tsv"]))
    out: dict = {}
    for r in sorted(rows, key=lambda r: r.hg):
        n = nseq.get(r.hg, 0) if nseq is not None else None
        res = model.bump(r.last, core.resources(cfg, stage, r.hg, table, n))
        out.setdefault((model.bump_reason(r.last), res), []).append(r.hg)
    return [(why, res, hgs) for (why, res), hgs in out.items()]


class _Box(Vertical, can_focus=True):
    pass


class ResubmitScreen(ModalScreen):
    # Focus: the box (not an Input) is focused on mount, so enter / y / escape are screen
    # bindings from the start.  Tab moves into the Inputs to edit; there, enter submits the
    # Input (-> dry run) and escape still reaches the screen.  `y` is marked priority, but a
    # focused Input still takes it as text in Textual 8, so a good dry run moves focus back to
    # the box (see _finish) and the next `y` submits.
    BINDINGS = [Binding("enter", "dry_run", "dry run"),
                Binding("y", "submit", "submit", priority=True),
                Binding("escape", "cancel", "cancel")]
    CSS = """
    ResubmitScreen { align: center middle; }
    #box { width: 90%; height: auto; border: round $warning; background: $surface; padding: 1; }
    Input { width: 14; }
    """

    def __init__(self, cfg: core.Config, stage: str, groups: list, raw: "dict | None" = None):
        super().__init__()
        self.cfg, self.stage, self.groups = cfg, stage, groups
        self.raw = raw if raw is not None else load_raw()
        self.submitted: list[str] = []
        self._dry_ok = False
        self._dry_per: "dict | None" = None     # the values the last dry run was computed from
        self._busy = False
        self._shown = ""
        self._result = ""
        self._refocus = None

    def compose(self) -> ComposeResult:
        with _Box(id="box"):
            yield Label(f"[b]resubmit · {self.stage}[/]  enter = dry run · y = submit · esc q = cancel")
            for i, (why, res, hgs) in enumerate(self.groups):
                with Horizontal():
                    yield Label(f"{len(hgs)} {core.unit(self.stage)} · {why or 'other'} · mem ")
                    yield Input(fmt_mem(res.mem_mb).replace(" ", "").replace("GB", "G")
                                .replace("MB", "M"), id=f"mem-{i}")
                    yield Label(" time ")
                    yield Input(fmt_time(res.time_min), id=f"time-{i}")
            yield Static("", id="out")

    def on_mount(self) -> None:
        self.query_one("#box").focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_dry_run()

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._busy:                         # the worker's values are already fixed
            return
        if self._dry_ok:                       # values moved since the dry run
            self._dry_ok = False
            self._out("[yellow]values changed: enter to re-run the dry run[/]")

    def _per_hg(self) -> dict:
        per: dict = {}
        for i, (_why, _res, hgs) in enumerate(self.groups):
            mem = core.parse_mem_mb(self.query_one(f"#mem-{i}", Input).value)
            t = model.parse_duration_min(self.query_one(f"#time-{i}", Input).value)
            if mem <= 0 or not t:
                raise ValueError(f"bad value in row {i}: memory and time must be > 0")
            for hg in hgs:
                per[hg] = {"mem_mb": mem, "time_min": t}
        return per

    def _build(self, dry_run: bool, per: dict):
        """Runs squeue/sacct via model.*: call from a worker thread only."""
        try:
            model.require_prefix(self.raw, self.cfg)
        except model.ModelError as e:
            return None, str(e)
        hgs = [hg for _w, _r, g in self.groups for hg in g]
        sel = model.select(self.cfg, self.stage, hgs, dry_run=dry_run)
        if not sel.selected:
            return None, "\n".join(sel.notes + ["nothing to submit"])
        msg = model.preflight(self.stage, self.cfg)
        if msg:
            return None, msg
        p = model.plan(self.cfg, self.stage, sel, per_hg=per)
        if p.errors:
            return None, "\n".join(f"{k} ({len(v)}): {model.show(v)}" for k, v in p.errors.items())
        return p, ""

    def _out(self, text: str) -> None:
        self._shown = text
        try:
            self.query_one("#out", Static).update(text)
        except Exception:                  # screen already dismissed
            pass

    def _post(self, fn, *args) -> None:
        """Run fn(*args) on the UI thread from a worker; drop it if the app is gone."""
        try:
            self.app.call_from_thread(fn, *args)
        except Exception:
            pass

    def _lock(self, locked: bool) -> None:
        try:
            for inp in self.query(Input):
                inp.disabled = locked
        except Exception:                  # screen already dismissed
            pass

    def _already_submitted(self) -> bool:
        if not self.submitted:
            return False
        self._out(self._result + "\n[yellow]already submitted · esc to close[/]")
        return True

    def _start(self, work, dry_run: bool) -> None:
        if self._busy or self._already_submitted():
            return
        try:
            per = self._per_hg()                               # reads the Inputs: UI thread
        except (ValueError, model.ModelError) as e:
            self._out(f"[red]{escape(str(e))}[/]")
            self._dry_ok = False
            return
        self._busy = True
        self._refocus = self.focused if isinstance(self.focused, Input) else None
        self._lock(True)
        self._out("[cyan]working…[/]")
        work(per)

    def _finish(self, text: str, dry_ok: bool = False, jids: "list | None" = None,
                per: "dict | None" = None, done: bool = False) -> None:
        """`done`: every array was submitted — close the dialog, say so, and let the app refresh
        (its dismiss callback reloads); a partial failure keeps the dialog open with the error."""
        if done:
            self.submitted = list(jids or [])
            self._busy = False
            from rich.text import Text      # the notes (e.g. skipped HGs) travel with the toast
            self.app.notify(Text.from_markup(text).plain, title=f"resubmit · {self.stage}",
                            markup=False, timeout=15)
            self.dismiss(self.submitted)
            return
        self._busy = False
        self._dry_ok = dry_ok
        self._dry_per = per if dry_ok else None
        if jids:
            self.submitted = jids
            self._result = text
        self._lock(False)
        try:
            if dry_ok:
                # A good dry run: move focus off the Inputs so the next `y` submits.  A focused
                # Input takes `y` as text (the priority binding does not win over it in
                # Textual 8), which silently replaced the value and voided the dry run.
                self.query_one("#box").focus()
            elif self._refocus is not None:      # a failed run: back to the field to fix it
                self._refocus.focus()
        except Exception:
            pass
        self._refocus = None
        self._out(text)

    def action_dry_run(self) -> None:
        if self._busy or self._already_submitted():
            return
        self._dry_ok = False
        self._start(self._dry_worker, dry_run=True)

    @work(thread=True, exclusive=True, group="resubmit")
    def _dry_worker(self, per: dict) -> None:
        try:
            p, err = self._build(True, per)
            if p is None:
                self._post(self._finish, f"[red]{escape(err)}[/]")
                return
            lines = ["[cyan]dry run[/] — nothing submitted yet; y to submit"] + [escape(n) for n in p.notes]
            for k, (res, ids_) in enumerate(p.groups):
                lines.append(f"array {k}: {len(ids_)} {core.unit(self.stage)} · {res.cpus} cpus · {fmt_mem(res.mem_mb)}"
                             f" · {fmt_time(res.time_min)} · {res.qos}")
        except Exception as e:             # never let a worker kill the app
            self._post(self._finish, f"[red]{escape(str(e))}[/]")
            return
        self._post(self._finish, "\n".join(lines), True, None, per)

    def action_submit(self) -> None:
        if self._busy or self._already_submitted():
            return
        if not self._dry_ok:
            if not self._shown:                    # keep an error the dry run already shows
                self._out("[yellow]run the dry run first (enter)[/]")
            return
        try:
            per = self._per_hg()
        except (ValueError, model.ModelError) as e:
            self._out(f"[red]{escape(str(e))}[/]")
            self._dry_ok = False
            return
        if per != self._dry_per:                   # edited since (or during) the dry run
            self._dry_ok = False
            self._out("[yellow]values changed since the dry run — press enter again[/]")
            return
        self._start(self._submit_worker, dry_run=False)

    @work(thread=True, exclusive=True, group="resubmit")
    def _submit_worker(self, per: dict) -> None:
        jids: list = []                            # filled by sbatch_all as arrays are queued
        notes: list = []
        w = None
        try:
            p, err = self._build(False, per)       # recomputed: state may have moved
            if p is None:
                self._post(self._finish, f"[red]{escape(err)}[/]")
                return
            notes = [escape(n) for n in p.notes]
            w = model.write_run(self.cfg, self.raw, p, dry_run=False)
            _ids, err = model.sbatch_all(w, jids)
        except Exception as e:             # never let a worker kill the app
            text = "\n".join(notes + ([f"[green]submitted {' '.join(jids)}[/]"
                                        f"{' · run dir ' + str(w.run_dir) if w else ''}"] if jids else [])
                              + [f"[red]{escape(str(e))}[/]"])
            self._post(self._finish, text, False, jids)
            return
        lines = notes + ([f"[green]submitted {' '.join(jids)}[/] · run dir {w.run_dir}"] if jids else [])
        if err:
            lines.append(f"[red]{escape(err)}[/]")
        self._post(self._finish, "\n".join(lines), False, jids, None, bool(jids) and not err)

    def action_cancel(self) -> None:
        if self._busy:                             # dismissing now would drop the result
            self.notify("still working — wait", severity="warning")
            return
        self.dismiss(self.submitted)


class RunScreen(ModalScreen):
    """S (Jobs tab, Setup): step 1 through step1run, in `druid run`'s order -- checks (history
    dir, refusal; its warnings shown in yellow), plan, preflight per stage, write, submit: search for the families not yet searched, each with a
    cluster array whose task i waits on search task i, plus cluster only for families already
    searched. enter = dry run (plans; writes and submits nothing), y = submit (planned again: the
    queue may have moved), esc = close. A submit's result stays shown (job ids, run dirs); the
    same box never submits twice. No Inputs: the box keeps the focus, so y is always this
    screen's key (ResubmitScreen's focused-Input caveat does not arise)."""
    BINDINGS = [Binding("enter", "dry_run", "dry run"),
                Binding("y", "submit", "submit", priority=True),
                Binding("escape", "cancel", "cancel")]
    CSS = """
    RunScreen { align: center middle; }
    RunScreen #box { width: 90%; height: auto; max-height: 90%; overflow-y: auto;
                     border: round $warning; background: $surface; padding: 1; }
    """
    PLANS = (("search", "search"), ("linked", "cluster after search"), ("only", "cluster"))

    def __init__(self, cfg: core.Config, raw: dict):
        super().__init__()
        self.cfg, self.raw = cfg, raw
        self.submitted: list[str] = []
        self._dry_ok = False
        self._busy = False
        self._shown = ""
        self._result = ""

    def compose(self) -> ComposeResult:
        with _Box(id="box"):
            yield Label("[b]run step 1 · search → cluster[/]  enter = dry run · y = submit · "
                        "esc q = cancel")
            yield Static("", id="out")

    def on_mount(self) -> None:
        self.query_one("#box").focus()

    def _plan(self, dry_run: bool):
        """(RunPlan, lines) when there is something to submit, else (None, lines): the refusal,
        the error, or the counts and "nothing to submit". Runs squeue and the tool checks: call
        from a worker thread only."""
        msg, warns = step1run.checks(self.raw, self.cfg)   # as the CLI: history dir, refusal
        if msg:
            return None, [f"[red]{escape(msg)}[/]"]
        warn = [f"[yellow]{escape(w)}[/]" for w in warns]
        try:
            rp = step1run.plan_run(self.cfg, self.raw, dry_run=dry_run)
        except model.ModelError as e:
            return None, warn + [f"[red]{escape(str(e))}[/]"]
        lines = warn + [escape(step1run.counts_line(rp.counts))] + [escape(n) for n in rp.notes]
        if not any(p is not None and p.groups for p in (rp.search, rp.linked, rp.only)):
            return None, lines + ["[yellow]nothing to submit[/]"]
        stages = (["search"] if rp.search is not None else []) + (
            ["cluster"] if rp.linked is not None or rp.only is not None else [])
        for stage in stages:                       # as the CLI: the message instead of a submit
            msg = model.preflight(stage, self.cfg)
            if msg:
                return None, lines + [f"[red]{escape(msg)}[/]"]
        return rp, lines

    def _out(self, text: str) -> None:
        self._shown = text
        try:
            self.query_one("#out", Static).update(text)
        except Exception:                  # screen already dismissed
            pass

    def _post(self, fn, *args) -> None:
        """Run fn(*args) on the UI thread from a worker; drop it if the app is gone."""
        try:
            self.app.call_from_thread(fn, *args)
        except Exception:
            pass

    def _already_submitted(self) -> bool:
        if not self.submitted:
            return False
        self._out(self._result + "\n[yellow]already submitted · esc to close[/]")
        return True

    def _start(self, work) -> None:
        self._busy = True
        self._out("[cyan]working…[/]")
        work()

    def _finish(self, text: str, dry_ok: bool = False, jids: "list | None" = None) -> None:
        self._busy = False
        self._dry_ok = dry_ok
        if jids:                                   # some or all arrays queued: never again here
            self.submitted = list(jids)
            self._result = text
        self._out(text)

    def action_dry_run(self) -> None:
        if self._busy or self._already_submitted():
            return
        self._dry_ok = False
        self._start(self._dry_worker)

    @work(thread=True, exclusive=True, group="run")
    def _dry_worker(self) -> None:
        try:
            rp, lines = self._plan(True)
            if rp is not None:
                lines = ["[cyan]dry run[/] — nothing submitted yet; y to submit"] + lines
                for attr, label in self.PLANS:
                    p = getattr(rp, attr)
                    if p is None or not p.groups:
                        continue
                    lines += [f"[dim]{label}: {escape(n)}[/]" for n in p.notes]
                    unit = core.unit(p.stage)
                    for k, (res, ids_) in enumerate(p.groups):
                        lines.append(f"{label} array {k}: {len(ids_)} {unit} · {res.cpus} cpus · "
                                     f"{fmt_mem(res.mem_mb)} · {fmt_time(res.time_min)} · {res.qos}")
        except Exception as e:             # never let a worker kill the app
            self._post(self._finish, f"[red]{escape(str(e))}[/]")
            return
        self._post(self._finish, "\n".join(lines), rp is not None)

    def action_submit(self) -> None:
        if self._busy or self._already_submitted():
            return
        if not self._dry_ok:
            if not self._shown:                    # keep an error the dry run already shows
                self._out("[yellow]run the dry run first (enter)[/]")
            return
        self._start(self._submit_worker)

    @work(thread=True, exclusive=True, group="run")
    def _submit_worker(self) -> None:
        lines: list = []
        jids: list = []
        try:
            rp, lines = self._plan(False)          # planned again: the queue may have moved
            if rp is None:
                self._post(self._finish, "\n".join(lines))
                return
            rw = step1run.write(self.cfg, self.raw, rp, dry_run=False)
            lines += [f"run dir {w.run_dir}" for w in (rw.search, rw.linked, rw.only) if w is not None]
            done, err = step1run.submit(rw)
            for stage, jid, n, after, res in done:
                jids.append(jid)
                lines.append(f"[green]submitted {jid}: {stage} {n} {core.unit(stage)}"
                             + (f" (after {after})" if after else "")
                             + f"[/] ({res.cpus} cpus, {fmt_mem(res.mem_mb)}, {fmt_time(res.time_min)})")
            if err:
                lines += [f"[red]{escape(line)}[/]" for line in err.splitlines()]
        except Exception as e:             # never let a worker kill the app
            lines.append(f"[red]{escape(str(e))}[/]")
        self._post(self._finish, "\n".join(lines), False, jids)

    def action_cancel(self) -> None:
        if self._busy:                             # dismissing now would drop the result
            self.notify("still working — wait", severity="warning")
            return
        self.dismiss(self.submitted)


class LogScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", "close"), Binding("q", "close", "close")]
    CSS = ("LogScreen { align: center middle; } "
           "#log { width: 95%; height: 90%; border: round $primary; background: $surface; }")

    def __init__(self, path: str, n: int = 200):
        super().__init__()
        parts = []
        for p in (Path(path), Path(path).with_suffix(".out")):
            if p.is_file():
                lines = p.read_text(errors="replace").splitlines()[-n:]
                parts.append(f"== {p}\n" + "\n".join(lines))
        self.text = "\n\n".join(parts) or f"no log at {path}"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="log"):
            yield Static(self.text, markup=False)

    def action_close(self) -> None:
        self.dismiss()
