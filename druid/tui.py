"""phylo tui: interactive view of step2 progress (Textual). Imported only by `phylo tui`."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import yaml
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static

from phylocli import core, history, model
from phylocli.common import fmt_mem, fmt_time

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
        self.by_stage: dict = {}
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
        # every applicable stage from ONE attempts read, ONE done scan, ONE squeue call, so
        # that stage changes and the detail panel need no subprocess on a key press
        done_map = core.report_status.done_by_stage(str(self.cfg.outdir), exp)
        live_map = model.live(core.expected(self.cfg)) or {}
        by_stage = {st: (model.hg_rows(self.cfg, st, exp, atts, done_map, live_map)
                         if core.applicable(self.cfg, st) else [])
                    for st in core.STAGES}
        arrays, sacct_known = model.array_rows()
        return dict(stages=stages, known=known, atts=atts, by_stage=by_stage, arrays=arrays,
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
        self.atts, self.by_stage = snap["atts"], snap["by_stage"]
        self.rows = self.by_stage.get(self.stage, [])
        banner = []
        if not snap["known"]:
            banner.append("squeue not on PATH: running jobs not detected")
        if not snap["sacct_known"]:
            banner.append("sacct not on PATH: task states unknown")
        self.query_one("#banner", Static).update(" · ".join(banner))
        self.sub_title = f"{self.stage} · {self.filter} · {snap['when']:%H:%M:%S}"
        st = self.query_one("#stages", DataTable)
        keep_stage = self.stage
        st.clear()
        for r in snap["stages"]:
            if r.applicable:
                st.add_row(r.stage, str(r.done), str(r.running), str(r.ready), str(r.blocked),
                           str(r.total), key=r.stage)
            else:
                st.add_row(r.stage, "n/a", "", "", "", "", key=r.stage)
        if keep_stage in core.STAGES:
            st.move_cursor(row=core.STAGES.index(keep_stage))
        ar = self.query_one("#arrays", DataTable)
        keep_row = ar.cursor_row
        ar.clear()
        for a in snap["arrays"]:
            c = a.counts
            ar.add_row(a.job, a.stage, str(a.n), str(c["done"]), str(c["running"]),
                       str(c["pending"]), str(c["failed"]), key=a.job)
        if snap["arrays"]:
            ar.move_cursor(row=min(keep_row, len(snap["arrays"]) - 1))
        self._fill_hgs()

    def visible(self) -> list:
        return [r for r in self.rows if r.state == self.filter]

    def _fill_hgs(self, keep: "str | None" = None) -> None:
        """Rebuild the HG table, keeping the cursor on the same HG (clear() resets it to row 0).
        `keep` overrides which HG to stay on (default: the one under the cursor now)."""
        t = self.query_one("#hgs", DataTable)
        keep = keep if keep is not None else self._cursor_hg()
        t.clear()
        for r in self.visible():
            n = self.nseq.setdefault(r.hg, core.nseq(self.cfg, r.hg))
            a = r.last
            t.add_row("●" if r.hg in self.selected else " ", r.hg, str(n),
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

    def _show_detail(self) -> None:
        hg = self._cursor_hg()
        box = self.query_one("#detail", Static)
        if hg is None:
            box.update("")
            return
        latest = history.latest_by_stage([a for a in self.atts if a.hg == hg])
        lines = [f"[b]{hg}[/]  {self.nseq.setdefault(hg, core.nseq(self.cfg, hg))} seqs", ""]
        for st in core.STAGES:
            rs = next((r for r in self.by_stage.get(st, []) if r.hg == hg), None)
            s_ = rs.state if rs else "n/a"
            a = latest.get(st)
            extra = (f"  {a.status} ({history.reason(a.status, a.exit)})  req {a.cpus}/{a.mem}/{a.time}"
                     f"  used {a.peak_rss}/{a.realtime}" if a else "")
            lines.append(f"{st:<12} [{STATE_STYLE.get(s_, 'white')}]{s_}[/]{extra}")
        a = latest.get(self.stage)
        if a is not None:
            lines += ["", f"log: {a.log}"]
        box.update("\n".join(lines))

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
        if event.row_key.value != self._key_at_cursor(t):
            return
        if t.id == "stages" and event.row_key.value in core.STAGES:
            if event.row_key.value != self.stage:
                self.stage = event.row_key.value
                self.selected.clear()
                self.rows = self.by_stage.get(self.stage, [])
                self._fill_hgs(keep="")
        elif t.id == "hgs":
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

    def action_resubmit(self) -> None:
        rows = [r for r in self.rows if r.hg in self.selected]
        if not rows:
            self.notify("nothing selected (space / a)", severity="warning")
            return
        groups = resource_groups(self.cfg, self.stage, rows)
        self.push_screen(ResubmitScreen(self.cfg, self.stage, groups),
                         lambda _jids: (self.selected.clear(), self.load_bg()))

    def action_log(self) -> None:
        hg = self._cursor_hg()
        a = next((r.last for r in self.rows if r.hg == hg), None) if hg else None
        if a is None:
            self.notify("no attempt recorded for this HG at this stage", severity="warning")
            return
        self.push_screen(LogScreen(a.log))


def resource_groups(cfg: core.Config, stage: str, rows: list) -> list:
    """[(reason, bumped Res, hgs)] for the selected rows, one entry per distinct pair."""
    table = core.load_resources_tsv(Path(cfg.params["resources_tsv"]))
    out: dict = {}
    for r in sorted(rows, key=lambda r: r.hg):
        res = model.bump(r.last, core.resources(cfg, stage, r.hg, table))
        out.setdefault((model.bump_reason(r.last), res), []).append(r.hg)
    return [(why, res, hgs) for (why, res), hgs in out.items()]


class _Box(Vertical, can_focus=True):
    pass


class ResubmitScreen(ModalScreen):
    # Focus: the box (not an Input) is focused on mount, so enter / y / escape are screen
    # bindings from the start.  Tab moves into the Inputs to edit; there, enter submits the
    # Input (-> dry run) and escape still reaches the screen.  `y` is a priority binding:
    # no valid memory/time value contains a y, so it can never be meant as typed text.
    BINDINGS = [Binding("enter", "dry_run", "dry run"),
                Binding("y", "submit", "submit", priority=True),
                Binding("escape", "cancel", "cancel")]
    CSS = """
    ResubmitScreen { align: center middle; }
    #box { width: 90%; height: auto; border: round $warning; background: $surface; padding: 1; }
    Input { width: 14; }
    """

    def __init__(self, cfg: core.Config, stage: str, groups: list):
        super().__init__()
        self.cfg, self.stage, self.groups = cfg, stage, groups
        self.submitted: list[str] = []
        self._dry_ok = False
        self._busy = False
        self._shown = ""

    def compose(self) -> ComposeResult:
        with _Box(id="box"):
            yield Label(f"[b]resubmit · {self.stage}[/]  enter = dry run · y = submit · esc = cancel")
            for i, (why, res, hgs) in enumerate(self.groups):
                with Horizontal():
                    yield Label(f"{len(hgs)} HGs · {why or 'other'} · mem ")
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
        hgs = [hg for _w, _r, g in self.groups for hg in g]
        sel = model.select(self.cfg, self.stage, hgs, dry_run=dry_run)
        if not sel.selected:
            return None, "\n".join(sel.notes + ["nothing to submit"])
        msg = model.preflight(self.stage)
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

    def _start(self, work, dry_run: bool) -> None:
        if self._busy:
            return
        try:
            per = self._per_hg()                               # reads the Inputs: UI thread
        except (ValueError, model.ModelError) as e:
            self._out(f"[red]{e}[/]")
            self._dry_ok = False
            return
        self._busy = True
        self._out("[cyan]working…[/]")
        work(per)

    def _finish(self, text: str, dry_ok: bool = False, jids: "list | None" = None) -> None:
        self._busy = False
        self._dry_ok = dry_ok
        if jids is not None:
            self.submitted = jids
        self._out(text)

    def action_dry_run(self) -> None:
        self._dry_ok = False
        self._start(self._dry_worker, dry_run=True)

    @work(thread=True, exclusive=True, group="resubmit")
    def _dry_worker(self, per: dict) -> None:
        try:
            p, err = self._build(True, per)
        except (ValueError, model.ModelError) as e:
            self._post(self._finish, f"[red]{e}[/]")
            return
        if p is None:
            self._post(self._finish, f"[red]{err}[/]")
            return
        lines = ["[cyan]dry run[/] — nothing submitted yet; y to submit"] + p.notes
        for k, (res, ids_) in enumerate(p.groups):
            lines.append(f"array {k}: {len(ids_)} HGs · {res.cpus} cpus · {fmt_mem(res.mem_mb)}"
                         f" · {fmt_time(res.time_min)} · {res.qos}")
        self._post(self._finish, "\n".join(lines), True)

    def action_submit(self) -> None:
        if self._busy:
            return
        if not self._dry_ok:
            if not self._shown:                    # keep an error the dry run already shows
                self._out("[yellow]run the dry run first (enter)[/]")
            return
        self._start(self._submit_worker, dry_run=False)

    @work(thread=True, exclusive=True, group="resubmit")
    def _submit_worker(self, per: dict) -> None:
        try:
            p, err = self._build(False, per)                  # recomputed: state may have moved
            if p is None:
                self._post(self._finish, f"[red]{err}[/]")
                return
            with open(os.environ.get("PHYLOCLI_CONFIG") or core.ROOT / "phylocli/config.yaml") as fh:
                raw = yaml.safe_load(fh.read())
            w = model.write_run(self.cfg, raw, p, dry_run=False)
            jids, err = model.sbatch_all(w)
        except (ValueError, model.ModelError) as e:
            self._post(self._finish, f"[red]{e}[/]")
            return
        self._post(self._finish,
                   (f"[green]submitted {' '.join(jids)}[/] · run dir {w.run_dir}" if jids else "")
                   + (f"\n[red]{err}[/]" if err else ""), False, jids)

    def action_cancel(self) -> None:
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
