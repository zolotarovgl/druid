"""phylo tui: interactive view of step2 progress (Textual). Imported only by `phylo tui`."""
from __future__ import annotations

from datetime import datetime

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.widgets import DataTable, Footer, Header, Static

from phylocli import core, history, model

FILTERS = ("failed", "ready", "running", "blocked", "done")
STATE_STYLE = {"done": "green", "running": "cyan", "ready": "yellow", "failed": "red",
               "blocked": "bright_black"}


class PhyloApp(App):
    TITLE = "phylocli"
    CSS = """
    Grid { grid-size: 2 2; grid-columns: 1fr 1fr; grid-rows: 1fr 1fr; }
    DataTable, #detail { border: round $primary; height: 100%; }
    #banner { height: auto; color: $warning; }
    """
    BINDINGS = [
        Binding("f", "cycle_filter", "filter"),
        Binding("space", "toggle", "select"),
        Binding("a", "select_all", "select all"),
        Binding("r", "resubmit", "resubmit"),
        Binding("l", "log", "log"),
        Binding("R", "refresh", "refresh"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self, cfg: core.Config, refresh_s: int = 30):
        super().__init__()
        self.cfg = cfg
        self.refresh_s = refresh_s
        self.stage = core.STAGES[0]
        self.filter = FILTERS[0]
        self.selected: set[str] = set()
        self.rows: list = []
        self.atts: list = []
        self.nseq: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="banner")
        with Grid():
            yield DataTable(id="stages", cursor_type="row")
            yield DataTable(id="hgs", cursor_type="row")
            yield DataTable(id="arrays", cursor_type="row")
            yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#stages", DataTable).add_columns("stage", "done", "run", "ready", "blk", "total")
        self.query_one("#hgs", DataTable).add_columns(" ", "HG", "seqs", "state", "last", "req", "used")
        self.query_one("#arrays", DataTable).add_columns("job", "stage", "HGs", "done", "run",
                                                          "pend", "fail")
        self.load_bg()
        self.set_interval(self.refresh_s, self.load_bg)

    # ---- data -------------------------------------------------------------------------------
    def _collect(self) -> dict:
        exp = core.expected(self.cfg)
        stages, known, _done = model.stage_rows(self.cfg, exp)
        atts = history.attempts(self.cfg)
        rows = model.hg_rows(self.cfg, self.stage, exp, atts)
        arrays, sacct_known = model.array_rows()
        return dict(stages=stages, known=known, atts=atts, rows=rows, arrays=arrays,
                    sacct_known=sacct_known, when=datetime.now())

    def load_now(self) -> None:
        self._apply(self._collect())

    @work(thread=True, exclusive=True)
    def load_bg(self) -> None:
        try:
            snap = self._collect()
        except model.ModelError as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        self.call_from_thread(self._apply, snap)

    def _apply(self, snap: dict) -> None:
        self.atts, self.rows = snap["atts"], snap["rows"]
        banner = []
        if not snap["known"]:
            banner.append("squeue not on PATH: running jobs not detected")
        if not snap["sacct_known"]:
            banner.append("sacct not on PATH: task states unknown")
        self.query_one("#banner", Static).update(" · ".join(banner))
        self.sub_title = f"{self.stage} · {self.filter} · {snap['when']:%H:%M:%S}"
        st = self.query_one("#stages", DataTable)
        st.clear()
        for r in snap["stages"]:
            if r.applicable:
                st.add_row(r.stage, str(r.done), str(r.running), str(r.ready), str(r.blocked),
                           str(r.total), key=r.stage)
            else:
                st.add_row(r.stage, "n/a", "", "", "", "", key=r.stage)
        ar = self.query_one("#arrays", DataTable)
        ar.clear()
        for a in snap["arrays"]:
            c = a.counts
            ar.add_row(a.job, a.stage, str(a.n), str(c["done"]), str(c["running"]),
                       str(c["pending"]), str(c["failed"]), key=a.job)
        self._fill_hgs()

    def visible(self) -> list:
        return [r for r in self.rows if r.state == self.filter]

    def _fill_hgs(self) -> None:
        t = self.query_one("#hgs", DataTable)
        t.clear()
        for r in self.visible():
            n = self.nseq.setdefault(r.hg, core.nseq(self.cfg, r.hg))
            a = r.last
            t.add_row("●" if r.hg in self.selected else " ", r.hg, str(n),
                      f"[{STATE_STYLE[r.state]}]{r.state}[/]",
                      model.bump_reason(a) if a else "–",
                      f"{a.mem}/{a.time}" if a else "–",
                      f"{a.peak_rss}/{a.realtime}" if a else "–", key=r.hg)
        self._show_detail()

    def _cursor_hg(self) -> "str | None":
        t = self.query_one("#hgs", DataTable)
        vis = self.visible()
        return vis[t.cursor_row].hg if vis and 0 <= t.cursor_row < len(vis) else None

    def _show_detail(self) -> None:
        hg = self._cursor_hg()
        box = self.query_one("#detail", Static)
        if hg is None:
            box.update("")
            return
        d = model.hg_detail(self.cfg, hg, self.atts)
        lines = [f"[b]{hg}[/]  {d.nseq} seqs", ""]
        for st, s in d.states.items():
            a = d.latest.get(st)
            extra = (f"  {a.status} ({history.reason(a.status, a.exit)})  req {a.cpus}/{a.mem}/{a.time}"
                     f"  used {a.peak_rss}/{a.realtime}" if a else "")
            lines.append(f"{st:<12} [{STATE_STYLE.get(s, 'white')}]{s}[/]{extra}")
        a = d.latest.get(self.stage)
        if a is not None:
            lines += ["", f"log: {a.log}"]
        box.update("\n".join(lines))

    # ---- events / actions -------------------------------------------------------------------
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key.value
        if event.data_table.id == "stages" and key in core.STAGES:
            if key != self.stage:
                self.stage = key
                self.selected.clear()
                self.rows = model.hg_rows(self.cfg, self.stage, None, self.atts)
                self._fill_hgs()
        elif event.data_table.id == "hgs":
            self._show_detail()

    def action_cycle_filter(self) -> None:
        self.filter = FILTERS[(FILTERS.index(self.filter) + 1) % len(FILTERS)]
        self._fill_hgs()

    def action_toggle(self) -> None:
        hg = self._cursor_hg()
        if hg:
            self.selected ^= {hg}
            self._fill_hgs()

    def action_select_all(self) -> None:
        self.selected = {r.hg for r in self.visible()}
        self._fill_hgs()

    def action_refresh(self) -> None:
        self.load_bg()

    def action_resubmit(self) -> None:      # Task 7
        self.notify("resubmit: not implemented yet")

    def action_log(self) -> None:           # Task 7
        self.notify("log: not implemented yet")
