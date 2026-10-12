"""Textual side: TreeView (the scrollable tree with a node cursor) and TreeScreen (help strip,
tree, prompt, status line).  Both are embeddable: no app-global state, no terminal handling."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical
from textual.geometry import Size
from textual.message import Message
from textual.screen import Screen
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Input, Static

from treeview import layout
from treeview.keys import KeysScreen
from treeview.model import TreeModel

KEYS = [
    ("Move", [("↑ ↓", "move the cursor"), ("pgup pgdn", "page up / down"),
              ("home end", "first / last node"), ("← →", "scroll sideways")]),
    ("Views", [("v", "outline ↔ cladogram"), ("l", "branch lengths to scale (cladogram)"),
               ("+ -", "tip spacing (- below 0: compact cladogram)"),
               ("t", "metadata columns on / off")]),
    ("Collapse", [("enter space", "collapse / expand the clade"),
                  ("s", "contract branches with support < x (polytomies)"),
                  ("m", "collapse single-species clades"), ("e", "expand all")]),
    ("Search", [("/", "search names and metadata"), ("n N", "next / previous hit")]),
    ("Colour", [("c", "cycle colour: species → each metadata column → species")]),
    ("Edit & export", [("r", "rename the clade"), ("w", "write the tree as shown (newick)")]),
    ("Other", [("?", "this list"), ("esc", "close the prompt / clear the search / back"),
               ("q", "quit")]),
]
HELP = "? keys · q quit"


class TreeView(ScrollView, can_focus=True):
    """The tree of a TreeModel in one of two views ("outline", "clado"), one row per visible
    node, the cursor on a node (kept across views and collapses).  Only the rows on screen are
    rendered (render_line)."""

    DEFAULT_CSS = """
    TreeView { border: round $primary; }
    TreeView:focus { border: round orange; }
    """
    BINDINGS = [
        Binding("up", "move(-1)", "up", show=False),
        Binding("down", "move(1)", "down", show=False),
        Binding("pageup", "page(-1)", "page up", show=False),
        Binding("pagedown", "page(1)", "page down", show=False),
        Binding("home", "jump(0)", "top", show=False),
        Binding("end", "jump(-1)", "bottom", show=False),
        Binding("enter,space", "toggle", "collapse"),
        Binding("v", "toggle_view", "view"),
        Binding("l", "toggle_lengths", "lengths"),
        Binding("plus", "gap(1)", "spacing +", show=False),
        Binding("minus", "gap(-1)", "spacing -", show=False),
        Binding("m", "collapse_species", "single-species"),
        Binding("e", "expand_all", "expand all"),
        Binding("t", "toggle_meta", "metadata"),
    ]

    def __init__(self, model: TreeModel, view: str = "clado", **kwargs):
        super().__init__(**kwargs)
        self.model = model
        self.view = view
        self.scaled = False                  # cladogram: branch lengths to scale
        self.gap = 0                         # cladogram: filler rows between node rows (0-3);
        #                                      -1 = compact (one row per leaf)
        self.cursor = 0                      # node id
        self.rows: list = []                 # (Text, node id); id None = a filler row.  Compact:
        #                                      (Text, [(node id, x0, x1), ...])
        self.order: list = []                # cursor stops (node ids) in ↑/↓ order
        self.pos: dict = {}                  # node id -> index in order
        self.rowof: dict = {}                # node id -> row (fillers excluded)
        self.span: dict = {}                 # compact: node id -> (x0, x1) highlighted on its row
        self.branch_width = 20               # cladogram branch columns (fit_rows)
        self._fit_w = 0                      # the view width the rows were fitted to
        self.show_meta = False               # metadata columns right of the labels (`t`)
        self.header: Optional[Text] = None   # their names: a fixed line 0 above the rows

    @property
    def compact(self) -> bool:
        return self.view == "clado" and self.gap < 0

    @property
    def _hd(self) -> int:
        """Lines above the rows: 1 while the metadata header is shown."""
        return 0 if self.header is None else 1

    # ---- rows ----------------------------------------------------------------------------------
    def rebuild(self) -> None:
        """Recompute the rows of the current view and state; the cursor stays on its node, or on
        its nearest visible ancestor when it was collapsed or contracted away."""
        m = self.model
        was = self.cursor
        # the columns the rows can use: inside the border and the vertical scrollbar, which is
        # 2 narrower than `size` on a tree taller than the screen
        view_w = self.scrollable_content_region.width or 80
        self._fit_w = view_w
        width = max(view_w - 40, 20)
        meta = self.show_meta and bool(m.meta_cols)
        if self.view == "outline":
            self.rows = layout.outline_rows(m, meta=meta)
        else:                                # names never off-screen: shorter branches instead
            width, rows = layout.fit_rows(m, view_w, width, scaled=self.scaled, gap=self.gap)
            self.rows = layout.with_meta(m, rows) if meta else rows
        self.branch_width = width
        self.header = layout.meta_header(m, self.rows) if meta else None
        if self.compact:                     # several nodes per row; the order is the cladogram's
            self.order = layout.clado_order(m)
            self.rowof, self.span = {}, {}
            for r, (_, stops) in enumerate(self.rows):
                for i, x0, x1 in stops:
                    self.rowof[i] = r
                    self.span[i] = (x0, x1)
        else:
            self.order = [i for _, i in self.rows if i is not None]
            self.rowof = {i: r for r, (_, i) in enumerate(self.rows) if i is not None}
            self.span = {}
        self.pos = {i: k for k, i in enumerate(self.order)}
        if self.cursor not in self.rowof:
            anc = [a for a in m.ancestors(self.cursor) if a in self.rowof]
            self.cursor = anc[0] if anc else self.order[0]
        w = max([t.cell_len for t, _ in self.rows] + [self.header.cell_len if self._hd else 1])
        # exactly as wide as the widest line: a row that fills the view does not scroll
        self.virtual_size = Size(w, len(self.rows) + self._hd)
        self.refresh()
        self.show_cursor()
        if self.cursor != was:                   # moved to an ancestor: the status line follows
            self.post_message(TreeView.Moved(self, self.cursor))

    def on_mount(self) -> None:
        self.rebuild()

    def on_resize(self) -> None:
        if self.view == "clado":
            self.rebuild()

    def watch_show_vertical_scrollbar(self, old: bool, new: bool) -> None:
        """The scrollbar appears (or goes) after the rows are set, narrowing (widening) the view
        without a resize: fit the cladogram to the width it has now."""
        if self.view == "clado" and self.scrollable_content_region.width != self._fit_w:
            self.call_after_refresh(self._refit)

    def _refit(self) -> None:
        if self.view == "clado" and self.scrollable_content_region.width != self._fit_w:
            self.rebuild()

    def render_line(self, y: int) -> Strip:
        """Line y on screen: the metadata header (line 0, scrolled horizontally only) when shown,
        then the rows from the scroll offset."""
        sx, sy = self.scroll_offset
        width = self.size.width
        if self.header is not None and y == 0:
            segs = list(self.header.render(self.app.console))
            return Strip(segs, self.header.cell_len).crop(sx, sx + width) \
                .extend_cell_length(width)
        r = sy + y - self._hd
        if r >= len(self.rows):
            return Strip.blank(width, self.rich_style)
        text = self.rows[r][0]
        if r == self.rowof.get(self.cursor, -1):           # a filler row is never the cursor's
            text = text.copy()
            span = self.span.get(self.cursor)              # compact: only the node's own cells
            if span:
                text.stylize("reverse", *span)
            else:
                text.stylize("reverse")
        segs = list(text.render(self.app.console))
        return Strip(segs, text.cell_len).crop(sx, sx + width).extend_cell_length(width)

    # ---- cursor --------------------------------------------------------------------------------
    @property
    def cursor_row(self) -> int:
        return self.rowof.get(self.cursor, 0)

    def set_cursor(self, i: int) -> None:
        self.cursor = i
        self.refresh()
        self.show_cursor()
        self.post_message(TreeView.Moved(self, i))

    def show_cursor(self) -> None:
        r = self.cursor_row
        h = max((self.scrollable_content_region.height or 1) - self._hd, 1)   # rows on screen
        if r < self.scroll_offset.y:
            self.scroll_to(y=r, animate=False)
        elif r >= self.scroll_offset.y + h:
            self.scroll_to(y=r - h + 1, animate=False)

    def action_move(self, d: int) -> None:
        if self.compact:                                 # through the node order, not the rows
            k = min(max(self.pos.get(self.cursor, 0) + d, 0), len(self.order) - 1)
            self.set_cursor(self.order[k])
            return
        r = min(max(self.cursor_row + d, 0), len(self.rows) - 1)
        step = 1 if d > 0 else -1
        while self.rows[r][1] is None:                   # skip fillers (the first and last rows
            r += step                                    # are nodes, so this stops in range)
        self.set_cursor(self.rows[r][1])

    def action_page(self, d: int) -> None:
        self.action_move(d * max(self.scrollable_content_region.height - 1 - self._hd, 1))

    def action_jump(self, k: int) -> None:
        self.set_cursor(self.order[k])

    # ---- state ---------------------------------------------------------------------------------
    def _changed(self) -> None:
        """Rebuild, then refresh the status line (drops a stale note such as `46 clades ...`)."""
        self.rebuild()
        self.post_message(TreeView.Moved(self, self.cursor))

    def action_toggle(self) -> None:
        self.model.toggle(self.cursor)
        self._changed()

    def action_toggle_view(self) -> None:
        self.view = "clado" if self.view == "outline" else "outline"
        self._changed()

    def action_toggle_lengths(self) -> None:
        if self.view == "clado":
            self.scaled = not self.scaled
            self._changed()

    def action_gap(self, d: int) -> None:
        """+/-: filler rows between the cladogram's rows, 0-3; `-` at 0 goes to compact (-1, one
        row per leaf), `+` there back to 0 (the outline has none of this)."""
        if self.view != "clado":
            return
        self.gap = min(max(self.gap + d, -1), 3)
        self.rebuild()
        self.post_message(TreeView.Note(
            self, "tip spacing " + ("compact" if self.gap < 0 else str(self.gap))))

    def action_collapse_species(self) -> None:
        n = self.model.collapse_single_species()
        self.rebuild()
        self.post_message(TreeView.Note(self, f"{n} single-species clades collapsed"))

    def action_expand_all(self) -> None:
        self.model.expand_all()
        self._changed()

    def action_toggle_meta(self) -> None:
        """t: the metadata columns (and their header line) on / off, in every view."""
        if not self.model.meta_cols:
            self.post_message(TreeView.Note(self, "no metadata (--meta)"))
            return
        self.show_meta = not self.show_meta
        self.rebuild()
        self.post_message(TreeView.Note(
            self, "metadata columns " + ("on" if self.show_meta else "off")))

    def goto(self, i: int) -> None:
        """Expand the path to node i and put the cursor on it (on its nearest shown ancestor when
        i is contracted)."""
        self.model.reveal(i)
        self.cursor = i
        self.rebuild()
        self.set_cursor(self.cursor)

    # ---- messages ------------------------------------------------------------------------------
    class Moved(Message):
        def __init__(self, view: "TreeView", node: int):
            super().__init__()
            self.view, self.node = view, node

    class Note(Message):
        def __init__(self, view: "TreeView", text: str):
            super().__init__()
            self.view, self.text = view, text


def describe(m: TreeModel, i: int) -> str:
    """Status line text of a node: full name, tips, support, branch length; for a tip with
    metadata, every field untruncated (`col=value · col=value`)."""
    if m.is_tip(i):
        head = f"{m.name[i]} · {m.species(i)}"
    else:
        head = f"{m.name[i] or 'clade'} · {m.ntips[i]} tips"
        if m.support[i] is not None:
            head += f" · support {m.support[i]:g}"
    head += f" · length {m.shown_dist(i):g}" if i else ""
    if i in m.meta:
        head += "".join(f" · {c}={v}" for c, v in zip(m.meta_cols, m.meta[i]))
    return head


class TreeScreen(Screen):
    """Help strip + TreeView + a one-line prompt (search / support threshold) + status line.
    esc: hide the prompt, else clear the search, else leave the screen (when pushed)."""

    DEFAULT_CSS = """
    TreeScreen #help { height: auto; color: $text-muted; margin: 0 1; }
    TreeScreen #prompt { height: 3; display: none; }
    TreeScreen #status { height: 1; margin: 0 1; }
    TreeScreen TreeView { height: 1fr; }
    """
    BINDINGS = [
        Binding("slash", "prompt('search')", "search"),
        Binding("s", "prompt('support')", "support"),
        Binding("r", "prompt('rename')", "rename"),
        Binding("w", "prompt('write')", "write"),
        Binding("c", "cycle_colour", "colour"),
        Binding("question_mark", "keys", "keys"),
        Binding("n", "hit(1)", "next hit", show=False),
        Binding("N", "hit(-1)", "previous hit", show=False),
        Binding("escape", "back", "back"),
    ]

    def __init__(self, model: TreeModel, view: str = "clado", title: str = "",
                 path: Optional[Path] = None, focus: Optional[int] = None, highlight=None,
                 **kwargs):
        super().__init__(**kwargs)
        self.model, self.start_view, self.title_text = model, view, title
        self.path = Path(path) if path is not None else None      # the input file (for `w`)
        self.focus_node = focus                   # the cursor's first node (an embedding caller)
        model.highlight = set(highlight or ())
        self.hits: list = sorted(model.highlight)  # n/N step through the highlighted tips
        self.hit = -1
        self.mode = ""

    def compose(self):
        yield Static(HELP, id="help")
        tv = TreeView(self.model, view=self.start_view, id="tree")
        tv.border_title = self.title_text
        yield tv
        yield Input(id="prompt")
        yield Static("", id="status")

    def on_mount(self) -> None:
        self.query_one(TreeView).focus()
        if self.focus_node is not None:           # after the first layout: goto rebuilds
            self.call_after_refresh(self.tree.goto, self.focus_node)
        self._status()
        m = self.model
        if m.has_meta:                    # queued behind the tree's own first messages
            self.tree.post_message(TreeView.Note(
                self.tree, f"metadata: {m.meta_matched}/{m.ntips[0]} tips matched"))

    @property
    def tree(self) -> TreeView:
        return self.query_one(TreeView)

    def _status(self, note: str = "") -> None:
        text = describe(self.model, self.tree.cursor)
        if self.hits:
            text += (f" · hit {self.hit + 1}/{len(self.hits)}" if self.hit >= 0
                     else f" · {len(self.hits)} hits (n/N)")
        self.query_one("#status", Static).update(Text(note or text))

    def on_tree_view_moved(self, event: TreeView.Moved) -> None:
        self._status()

    def on_tree_view_note(self, event: TreeView.Note) -> None:
        self._status(event.text)

    def action_prompt(self, mode: str) -> None:
        inp = self.query_one("#prompt", Input)
        value = {"search": "", "support": "50"}.get(mode, "")
        if mode == "rename":
            if self.model.is_tip(self.tree.cursor):
                self._status("tips keep their names")
                return
            value = self.model.name[self.tree.cursor]
        elif mode == "write":
            value = str(self._default_out())
        self.mode = mode
        search = "search names and metadata" if self.model.meta_cols else "search names"
        inp.border_title = {"search": search, "support": "contract support <",
                            "rename": "rename clade", "write": "write newick to"}[mode]
        inp.value = value
        inp.display = True
        inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        inp = self.query_one("#prompt", Input)
        inp.display = False
        self.tree.focus()
        if self.mode == "search":
            self.hits, self.hit = self.model.search(event.value), -1
            if not self.hits:
                self._status(f"no match: {event.value}")
                return
            self.action_hit(1)
        elif self.mode == "rename":
            try:
                self.model.rename(self.tree.cursor, event.value)
            except ValueError:
                self._status(f"invalid name: {event.value}")
                return
            self.tree._changed()                  # redraw the label, then the status line follows
        elif self.mode == "write":
            self._write(event.value.strip())
        else:
            try:
                x = float(event.value)
            except ValueError:
                self._status(f"not a number: {event.value}")
                return
            n = self.model.contract_below_support(x)
            self.tree.rebuild()
            # posted, not set directly: rebuild() may have queued a Moved that would overwrite it
            note = f"{n} branches with support < {x:g} contracted"
            self.tree.post_message(TreeView.Note(self.tree, note))

    def action_cycle_colour(self) -> None:
        """c: species colour → each metadata column in order → species colour."""
        m = self.model
        if not m.meta_cols:
            self._status("no metadata columns")
            return
        modes = [""] + m.meta_cols
        nxt = modes[(modes.index(m.colour_by) + 1) % len(modes)]
        n = m.set_colour_by(nxt)
        self.tree.rebuild()
        note = f"colour: {nxt} · {n} values" if nxt else "colour: species"
        self.tree.post_message(TreeView.Note(self.tree, note))      # after rebuild's Moved

    def action_keys(self) -> None:
        self.app.push_screen(KeysScreen("treeview keys", KEYS))

    def _default_out(self) -> Path:
        """`<input stem>.named.nwk` next to the input, else `tree.named.nwk` in the cwd."""
        if self.path is None:
            return Path("tree.named.nwk")
        return self.path.with_name(self.path.stem + ".named.nwk")

    def _write(self, value: str) -> None:
        if not value:
            self._status("no file name")
            return
        out = Path(value).expanduser()
        if self.path is not None and out.resolve() == self.path.resolve():
            self._status("will not overwrite the input")
            return
        try:
            out.write_text(self.model.to_newick() + "\n")
        except OSError as e:
            self._status(f"cannot write {out}: {e.strerror or e}")
            return
        self._status(f"wrote {out}")

    def action_hit(self, d: int) -> None:
        if not self.hits:
            return
        self.hit = (self.hit + d) % len(self.hits)
        self.tree.goto(self.hits[self.hit])
        self._status()

    def action_back(self) -> None:
        inp = self.query_one("#prompt", Input)
        if inp.display:
            inp.display = False
            self.tree.focus()
        elif self.hits or self.model.highlight:
            self.hits, self.hit = [], -1
            if self.model.highlight:
                self.model.highlight = set()
                self.tree.rebuild()
            self._status()
        elif len(self.app.screen_stack) > 1 and self.app.screen is self:
            self.app.pop_screen()
