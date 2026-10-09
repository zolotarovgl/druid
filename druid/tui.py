"""phylo tui: interactive view of step1 + step2 progress (Textual). Imported only by `phylo tui`."""
from __future__ import annotations

import collections
import os
from datetime import datetime
from pathlib import Path

import yaml
from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static
from textual.worker import get_current_worker

from phylocli import core, history, model
from phylocli.common import fmt_mem, fmt_time


def load_raw() -> dict:
    """The raw config.yaml (same path logic as `phylo submit`); written into each run dir."""
    p = Path(os.environ.get("PHYLOCLI_CONFIG") or core.ROOT / "phylocli/config.yaml")
    return yaml.safe_load(p.read_text())

FILTERS = ("actionable", "failed", "ready", "running", "blocked", "done")
ACTIONABLE = ("failed", "ready")      # the "actionable" filter shows failed + ready HGs
PANE_TITLES = {"#overview": "Overview", "#stages": "1 Stages", "#hgs": "2 HGs",
               "#arrays": "3 Arrays", "#detail": "4 Detail"}
STATE_STYLE = {"done": "green", "running": "cyan", "ready": "yellow", "failed": "red",
               "blocked": "bright_black"}
# Stages the TUI shows (overview columns, stages panel, HG-view data): search/cluster in front.
TUI_STAGES = core.STAGES
OV_SEP = "│"
# Overview stage columns: step1 (families) | step2 (HGs); None = the one-character separator column.
OV_COLUMNS = [*core.FAMILY_STAGES, None, *core.HG_STAGES]
# Top header row (Grygoriy, 09/10/2026): block names over the first two columns of each block.
OV_TOP = {core.FAMILY_STAGES[0]: "step1 ·", core.FAMILY_STAGES[1]: "families",
          core.HG_STAGES[0]: "step2 ·", core.HG_STAGES[1]: "HGs"}


def ov_column(stage: str) -> int:
    """Overview column of `stage` (after the group and HGs columns, skipping the separator)."""
    return 2 + OV_COLUMNS.index(stage)


def stage_at_column(col: int) -> "str | None":
    """The stage of an overview column; None for group, HGs and the separator (not a stage).
    The one column->stage mapping: enter, cursor restore and the `s` sort use it."""
    return OV_COLUMNS[col - 2] if 2 <= col < 2 + len(OV_COLUMNS) else None


class PhyloApp(App):
    TITLE = "phylocli"
    CSS = """
    #hgview { grid-size: 2 2; grid-columns: 1fr 1fr; grid-rows: 1fr 1fr; }
    #hgview DataTable, #detail { border: round $primary; height: 100%; }
    #banner { height: auto; color: $warning; }
    #ov { height: 1fr; }
    #overview { height: 1fr; border: round $primary; }
    #ovfoot { height: auto; }
    #hgview { height: 1fr; }
    #hgview DataTable:focus, #overview:focus { border: round orange; }
    #hgview.loading { opacity: 40%; }
    """
    BINDINGS = [
        Binding("escape", "back", "overview"),
        Binding("c", "by_category", "category"),
        Binding("f", "cycle_filter", "filter / family"),
        Binding("space", "toggle", "select"),
        Binding("a", "select_all", "select all"),
        Binding("r", "resubmit", "resubmit"),
        Binding("l", "log", "log"),
        Binding("R", "refresh", "refresh"),
        Binding("q", "quit", "quit"),
    ]

    OV_BAR = 10
    OV_GLYPHS = (("█", "green"), ("▒", "cyan"), ("▓", "yellow"), ("░", "bright_black"))

    def __init__(self, cfg: core.Config, refresh_s: int = 30, raw: "dict | None" = None,
                 start: str = "overview"):
        super().__init__()
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
        self._banner_text = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="banner")
        with Vertical(id="ov"):
            yield DataTable(id="overview", cursor_type="cell", header_height=2)   # step1/step2 header
            yield Static("", id="ovfoot")
        with Grid(id="hgview"):
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
        for wid, title in PANE_TITLES.items():   # names in the top-left border, to refer to them
            self.query_one(wid).border_title = title
        self._show_view()
        self.load_bg()
        self.set_interval(self.refresh_s, self.load_bg)

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
            fatts = history.family_attempts(self.cfg)
            # every applicable stage from ONE attempts read, ONE done scan, ONE squeue call, so
            # that stage changes and the detail panel need no subprocess on a key press
            by_stage = {st: (model.hg_rows(self.cfg, st, exp,
                                           fatts if st in core.FAMILY_STAGES else atts,
                                           done_map, lv)
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
                self.call_from_thread(self.notify, str(e), severity="error", markup=False)
            return
        if worker.is_cancelled:              # superseded by a newer refresh
            return
        self.call_from_thread(self._apply, snap)

    def _set_banner(self, text: str) -> None:
        self._banner_text = text
        self.query_one("#banner", Static).update(text)

    def _apply(self, snap: dict) -> None:
        self._ov_inputs = snap["ov_inputs"]
        self.hg_count = snap["hg_count"]
        if snap["by"] != self.by:            # c/f pressed while this was being collected
            self._regroup()
        else:
            self._fill_overview(snap["ov_rows"])
        hg = snap["hg"]
        banner = []
        if not snap["known"]:
            banner.append("squeue not on PATH: running jobs not detected")
        banner += [escape(w) for w in snap["fam_warn"]]
        if hg is not None and not hg["sacct_known"]:
            banner.append("sacct not on PATH: task states unknown")
        if hg is None and self.view == "hgs" and not self.by_stage:
            banner.append("loading history…")
        self._set_banner(" · ".join(banner))
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
        if self.filter == "actionable":
            rows = [r for r in self.rows if r.state in ACTIONABLE]
        else:
            rows = [r for r in self.rows if r.state == self.filter]
        if self.group is not None:          # search / cluster list families, the rest HGs
            key = model.fam_group_key if self.stage in core.FAMILY_STAGES else model.group_key
            rows = [r for r in rows if key(r.hg, self.by) == self.group]
        return rows

    # ---- overview ---------------------------------------------------------------------------
    def _show_view(self) -> None:
        self.query_one("#ov").display = self.view == "overview"
        self.query_one("#hgview").display = self.view == "hgs"
        self.query_one("#overview" if self.view == "overview" else "#hgs").focus()

    def _fill_overview(self, rows: list) -> None:
        self.ov_rows = rows
        t = self.query_one("#overview", DataTable)
        keep = self._key_at_cursor(t)
        col = t.cursor_column
        if col >= 2 and stage_at_column(col) is None:      # never restore onto the separator
            col += 1
        if not t.columns:
            t.add_columns(Text("\ngroup"), Text("\nHGs"),
                          *(Text(f"{OV_SEP}\n{OV_SEP}") if st is None
                            else Text(f"{OV_TOP.get(st, '')}\n{st}") for st in OV_COLUMNS))
        t.clear()
        for r in rows:
            cells = []
            for st in OV_COLUMNS:
                if st is None:
                    cells.append(OV_SEP)
                    continue
                c = r.per_stage.get(st)
                if c is None:
                    cells.append("n/a")
                    continue
                n = model.bar_segments(c, self.OV_BAR)
                cells.append("".join(f"[{fg}]{ch * k}[/]"
                                     for (ch, fg), k in zip(self.OV_GLYPHS, n) if k))
            t.add_row(r.group, str(r.total), *cells, key=r.group)
        keys = [r.group for r in rows]
        t.move_cursor(row=keys.index(keep) if keep in keys else 0, column=col)
        self._overview_footer()

    def _overview_footer(self) -> None:
        key = self._key_at_cursor(self.query_one("#overview", DataTable))
        r = next((x for x in self.ov_rows if x.group == key), None)
        if r is None:
            return
        parts = [f"{st} {c[0]}/{c[1]}/{c[2]}/{c[3]}" for st, c in r.per_stage.items() if c]
        self.query_one("#ovfoot", Static).update(
            f"[b]{escape(r.group)}[/] {r.total} HGs · {r.n_fams} families · "
            "done/running/ready/blocked: " + " · ".join(parts)
            + "\n█ done ▒ running ▓ ready/failed ░ blocked · search/cluster count families · "
              "enter: open · c/f: category/family"
            + " · default view: failed+ready")

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
        self._show_view()
        if not self.by_stage:
            self._set_banner("loading history…")
        self.query_one("#hgview").set_class(not self.by_stage, "loading")   # grey until data
        self._fill_stages()
        self._fill_hgs(keep="")
        self.load_bg()

    def check_action(self, action: str, parameters: tuple) -> "bool | None":
        """Footer shows only the keys of the current view."""
        if action in ("by_category",):
            return self.view == "overview"
        if action in ("back", "toggle", "select_all", "resubmit", "log"):
            return self.view == "hgs"
        return True

    def action_back(self) -> None:
        if self.view == "hgs":
            self.view = "overview"
            self._show_view()

    def action_by_category(self) -> None:
        if self.view == "overview":
            self.by = "category"
            self._regroup()

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        if event.data_table.id != "overview" or self.view != "overview":
            return
        stage = stage_at_column(event.coordinate.column)   # None: group, HGs or │ -> current stage
        self.open_group(event.cell_key.row_key.value, stage)

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        if event.data_table.id == "overview":
            self._overview_footer()

    def _fill_hgs(self, keep: "str | None" = None) -> None:
        """Rebuild the HG table, keeping the cursor on the same HG (clear() resets it to row 0).
        `keep` overrides which HG to stay on (default: the one under the cursor now)."""
        t = self.query_one("#hgs", DataTable)
        keep = keep if keep is not None else self._cursor_hg()
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
                self._fill_hgs(keep="")
        elif t.id == "hgs":
            self._show_detail()

    def action_cycle_filter(self) -> None:
        if self.view == "overview":
            self.by = "family"
            self._regroup()
            return
        self._auto_filter = False
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
        groups = resource_groups(self.cfg, self.stage, rows, self.nseq)
        self.push_screen(ResubmitScreen(self.cfg, self.stage, groups, self.raw),
                         lambda _jids: (self.selected.clear(), self.load_bg()))

    def action_log(self) -> None:
        hg = self._cursor_hg()
        a = next((r.last for r in self.rows if r.hg == hg), None) if hg else None
        if a is None:
            self.notify("no attempt recorded for this HG at this stage", severity="warning")
            return
        self.push_screen(LogScreen(a.log))


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
            yield Label(f"[b]resubmit · {self.stage}[/]  enter = dry run · y = submit · esc = cancel")
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
                per: "dict | None" = None) -> None:
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
                lines.append(f"array {k}: {len(ids_)} {core.unit(self.stage)} ·{res.cpus} cpus · {fmt_mem(res.mem_mb)}"
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
