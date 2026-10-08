# phylocli TUI overview screen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `phylo tui` opens on a per-category (or per-family) overview of stage progress; `enter` on a row opens the existing HG panels restricted to that row; the slow attempt history is read only in the HG view.

**Architecture:** `model.group_rows` buckets the same done / running / ready / blocked sets `stage_rows` computes, by category or family; a shared `model.bar_segments` gives the CLI and the TUI one rounding rule. `PhyloApp` gains an overview table shown first and a `view` switch; its HG-view code stays as it is, filtered by the opened group.

**Tech Stack:** Python ≥ 3.9, Textual 8.2.8 (optional), pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-phylocli-tui-design.md` — sections "Overview — the first screen", "HG view", "Refresh" (amended 09/10/2026).

**Repo / branch:** worktree `~/Documents/projects/phylogenies/phylocli-wt`, branch `phylocli` (HEAD `89f2bfd` + the uncommitted spec amendment, which the controller commits before Task 1).

## Global Constraints

- CLI output text and exit codes of `status`, `missing`, `submit`, `jobs`, `queue`, `_run` stay byte-identical; the 118 original tests (test_cli/test_core/test_history/test_runner as of 8fa45ec) pass unmodified.
- Branch tests in `test_tui.py` may change ONLY by adding `start="hgs"` to `PhyloApp(...)` constructions (the HG view was the old first screen); no assertion changes.
- Python 3.9-safe (`from __future__ import annotations`; no `match`; no `X | Y` outside annotations). Textual imported only in `tui.py`.
- The overview never calls `history.attempts` (spec: "the overview reads only output files + squeue").
- `ALL` row numbers equal `model.stage_rows` exactly.
- Test commands (both must pass):
  `python3 -m pytest phylocli/tests -q -p no:cacheprovider` and
  `/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-phylogenies/3dad6ea4-c859-4fe6-b319-93a358944ac8/scratchpad/py39/bin/python -m pytest phylocli/tests -q -p no:cacheprovider` (baseline 170).
- Commit on `phylocli`, message ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; Edit/Write tools, never sed.

## Review Focus

1. **Grouping key for ids with extra dots** — family = `hg.rsplit(".", 1)[0]` (as `missing --per-fam`), category = `hg.split(".", 1)[0]`; a family name containing `.` must still group correctly. → Task 1 test with `adh.Cad.herin.HG1`.
2. **A refresh while in the HG view must not jump back to the overview or lose the opened group** → Task 2 test.
3. **`esc` back to the overview keeps the overview cursor on the row that was opened** → Task 2 test.
4. **`f` means "family" on the overview but "cycle filter" in the HG view** — the key must do the right thing per view → Task 2 tests for both.
5. **Opening a group before any HG-view data exists** shows "loading history…" and an empty list, not a crash or stale rows from another group → Task 2 test.

---

### Task 1: `model.bar_segments`, `group_key`, `group_rows`

**Files:**
- Modify: `phylocli/model.py` (append), `phylocli/phylo.py` (`_bar` uses `bar_segments`)
- Test: `phylocli/tests/test_model.py` (append)

**Interfaces:**
- Produces:
  - `bar_segments(counts: tuple, width: int) -> list[int]` — largest-remainder split, sums to `width` (empty list when total 0)
  - `group_key(hg: str, by: str) -> str` — `by ∈ {"category", "family"}`
  - `@dataclass GroupRow: group: str; total: int; per_stage: dict` — `per_stage[stage]` = `(done, running, ready, blocked)` or `None` when not applicable
  - `group_rows(cfg, exp: set[str], by: str = "category", done: dict | None = None, lv: dict | None = None) -> tuple[list[GroupRow], bool]` — first row `group == "ALL"`, then groups sorted by `(-total, group)`; bool = squeue known

- [ ] **Step 1: Failing tests** (append to `test_model.py`):

```python
def test_bar_segments():
    assert model.bar_segments((1, 0, 1, 0), 10) == [5, 0, 5, 0]
    assert sum(model.bar_segments((7, 1, 1, 1), 30)) == 30
    assert model.bar_segments((0, 0, 0, 0), 10) == []


def test_group_key():
    assert model.group_key("tfs.T-box.HG1", "category") == "tfs"
    assert model.group_key("tfs.T-box.HG1", "family") == "tfs.T-box"
    assert model.group_key("adh.Cad.herin.HG12", "family") == "adh.Cad.herin"


def test_group_rows_all_equals_stage_rows(cli):
    cfg = _cfg()
    exp = core.expected(cfg)
    rows, known = model.group_rows(cfg, exp, "category")
    srows, _k, _d = model.stage_rows(cfg, exp)
    assert rows[0].group == "ALL" and rows[0].total == len(exp)
    for s in srows:
        got = rows[0].per_stage[s.stage]
        assert got == ((s.done, s.running, s.ready, s.blocked) if s.applicable else None)
    assert [r.group for r in rows] == ["ALL", "tfs"]


def test_group_rows_family_sum_to_all(cli):
    cfg = _cfg()
    exp = core.expected(cfg)
    rows, _k = model.group_rows(cfg, exp, "family")
    assert [r.group for r in rows] == ["ALL", "tfs.A", "tfs.C_x"]
    for st, allc in rows[0].per_stage.items():
        if allc is None:
            continue
        assert tuple(sum(r.per_stage[st][i] for r in rows[1:]) for i in range(4)) == allc
```

(The fixture's expected HGs are `tfs.A.HG1`, `tfs.A.HG11`, `tfs.C_x.HG1`; `tfs.A` has 2 HGs, `tfs.C_x` 1, so family order is `tfs.A`, `tfs.C_x`.)

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_model.py -q -p no:cacheprovider` — Expected: FAIL, `AttributeError: ... 'bar_segments'`.

- [ ] **Step 3: Implement** (append to `model.py`):

```python
def bar_segments(counts, width: int) -> list[int]:
    """Largest-remainder split of `width` cells over `counts`; [] when all are 0."""
    total = sum(counts)
    if total == 0:
        return []
    exact = [width * c / total for c in counts]
    n = [int(x) for x in exact]
    for i in sorted(range(len(n)), key=lambda i: exact[i] - n[i], reverse=True)[:width - sum(n)]:
        n[i] += 1
    return n


def group_key(hg: str, by: str) -> str:
    """category = first id part (tfs); family = id without the HG part (tfs.T-box)."""
    return hg.split(".", 1)[0] if by == "category" else hg.rsplit(".", 1)[0]


@dataclass
class GroupRow:
    group: str
    total: int
    per_stage: dict


def group_rows(cfg: core.Config, exp: set[str], by: str = "category",
               done: dict | None = None, lv: dict | None = None):
    """(rows, squeue_known): per-group done/running/ready/blocked per stage, from output files
    and squeue only (no attempt history). rows[0] is ALL and equals stage_rows()."""
    done = core.report_status.done_by_stage(str(cfg.outdir), exp) if done is None else done
    known = True
    if lv is None:
        lv = live(exp)
        known = lv is not None
        lv = lv or {}
    state: dict[str, dict[str, int]] = {}          # stage -> hg -> 0 done 1 running 2 ready 3 blocked
    for st in core.STAGES:
        if not core.applicable(cfg, st):
            continue
        d = done.get(st, set())
        todo = exp - d
        running = todo & lv.get(st, set())
        ready = core.ready_set(cfg, st, todo - running)
        state[st] = {hg: (0 if hg in d else 1 if hg in running else 2 if hg in ready else 3)
                     for hg in exp}
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for hg in exp:
        groups[group_key(hg, by)].append(hg)

    def row(name: str, hgs) -> GroupRow:
        per = {}
        for st in core.STAGES:
            if st not in state:
                per[st] = None
                continue
            c = [0, 0, 0, 0]
            for hg in hgs:
                c[state[st][hg]] += 1
            per[st] = tuple(c)
        return GroupRow(name, len(hgs), per)

    rows = [row("ALL", exp)] + [row(g, h) for g, h in
                                sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    return rows, known
```

In `phylo.py`, replace the rounding inside `_bar` (keep its signature, docstring and return) with:

```python
def _bar(done: int, running: int, ready: int, blocked: int, mode: str = "status") -> str:
    """Fixed-width bar split into done / running (in SLURM now) / ready to run / blocked;
    largest-remainder rounding so the segments always add up to BAR_WIDTH."""
    n = model.bar_segments((done, running, ready, blocked), BAR_WIDTH)
    if not n:
        return ""
    return "".join(typer.style(ch * k, fg=fg) for (ch, fg), k in zip(BAR_STYLES[mode], n))
```

- [ ] **Step 4: Run both suites** — Expected: 174 passed on both (170 + 4).

- [ ] **Step 5: Commit** — `phylocli/model.py`, `phylocli/phylo.py`, `phylocli/tests/test_model.py`; message `phylocli: model.group_rows (per category/family stage counts) and shared bar_segments`.

---

### Task 2: overview as the first TUI view; HG view per group; history only in the HG view

**Files:**
- Modify: `phylocli/tui.py`, `phylocli/tests/test_tui.py`, `phylocli/README.md` (`## phylo tui` section)

**Interfaces:**
- Consumes: `model.group_rows`, `model.group_key`, `model.bar_segments`, `model.GroupRow` (Task 1)
- Produces: `PhyloApp(cfg, refresh_s=30, raw=None, start="overview")`; attributes `view ∈ {"overview","hgs"}`, `by ∈ {"category","family"}`, `group: str | None` (None = ALL), `ov_rows: list[model.GroupRow]`; method `open_group(name: str)`; `visible()` filters by state AND by `group`.

- [ ] **Step 1: Existing tests** — in `test_tui.py`, add `start="hgs"` to every `tui.PhyloApp(...)` construction (including the `_failed_app` helper). Run `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider` — Expected: FAIL, `TypeError: ... unexpected keyword argument 'start'` (proves every construction was found).

- [ ] **Step 2: New failing tests** (append to `test_tui.py`):

```python
def _counting_attempts(monkeypatch):
    from phylocli import history
    calls = {"n": 0}
    real = history.attempts

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(history, "attempts", counted)
    return calls


def test_overview_is_first_and_reads_no_history(cli, monkeypatch):
    calls = _counting_attempts(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert app.view == "overview"
            assert [r.group for r in app.ov_rows] == ["ALL", "tfs"]
            exp = core.expected(_cfg())
            srows, _k, _d = tui.model.stage_rows(_cfg(), exp)
            a = next(s for s in srows if s.stage == "align")
            assert app.ov_rows[0].per_stage["align"] == (a.done, a.running, a.ready, a.blocked)
    _run(go())
    assert calls["n"] == 0


def test_overview_family_toggle(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()
            assert app.by == "family" and [r.group for r in app.ov_rows] == ["ALL", "tfs.A", "tfs.C_x"]
            await pilot.press("c")
            await pilot.pause()
            assert app.by == "category"
    _run(go())


def test_open_group_restricts_hgs_and_esc_returns(cli, monkeypatch):
    calls = _counting_attempts(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()
            app.query_one("#overview").move_cursor(row=1)          # tfs.A
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.view == "hgs" and app.group == "tfs.A"
            app.load_now()
            await pilot.pause()
            assert calls["n"] >= 1
            app.filter = "done"
            app._fill_hgs()
            assert {r.hg for r in app.visible()} <= {"tfs.A.HG1", "tfs.A.HG11"}
            app.filter = "ready"
            app._fill_hgs()
            assert "tfs.C_x.HG1" not in {r.hg for r in app.visible()}
            await pilot.press("f")                                   # HG view: f = cycle filter
            assert app.view == "hgs" and app.by == "family"
            await pilot.press("escape")
            await pilot.pause()
            assert app.view == "overview"
            assert app.query_one("#overview").cursor_row == 1
    _run(go())


def test_enter_on_stage_cell_opens_that_stage_with_failed_filter(cli, monkeypatch):
    assert cli(["submit", "align", "tfs.A.HG11", "tfs.C_x.HG1"]).exit_code == 0
    monkeypatch.setenv("FAKE_SACCT", SACCT_OOM)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            ov = app.query_one("#overview")
            ov.move_cursor(row=0, column=2 + core.STAGES.index("align"))   # ALL × align
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            assert app.view == "hgs" and app.stage == "align" and app.filter == "failed"
            assert app.focused is app.query_one("#hgs")
            assert [r.hg for r in app.visible()] == ["tfs.C_x.HG1"]
            await pilot.press("space", "r")                                # select and resubmit
            await pilot.pause()
            assert isinstance(app.screen, tui.ResubmitScreen)
    _run(go())


def test_refresh_in_hg_view_stays_in_group(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.open_group("tfs")
            await pilot.pause()
            app.load_now()
            await pilot.pause()
            assert app.view == "hgs" and app.group == "tfs"
    _run(go())


def test_open_group_before_hg_data_shows_loading(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            app.by_stage = {}                       # no HG-view snapshot yet
            app.open_group("tfs")
            await pilot.pause()
            assert app.visible() == []
            assert "loading history" in app._banner_text
    _run(go())
```

- [ ] **Step 3: Run** `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider` — Expected: the 6 new tests FAIL (`AttributeError: 'PhyloApp' object has no attribute 'view'` or similar); the edited old tests fail on `start=`.

- [ ] **Step 4: Implement in `tui.py`.**

4a. `__init__` gains `start: str = "overview"` and sets
```python
        self.view = start
        self.by = "category"
        self.group: "str | None" = None
        self.ov_rows: list = []
        self._banner_text = ""
```

4b. `compose`: put the overview in front of the existing grid:
```python
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="banner")
        with Vertical(id="ov"):
            yield DataTable(id="overview", cursor_type="row")
            yield Static("", id="ovfoot")
        with Grid(id="hgview"):
            yield DataTable(id="stages", cursor_type="row")
            yield DataTable(id="hgs", cursor_type="row")
            yield DataTable(id="arrays", cursor_type="row")
            yield Static("", id="detail")
        yield Footer()
```
CSS: add `#overview { height: 1fr; border: round $primary; }  #ovfoot { height: auto; }`.
In `on_mount`, after the existing `add_columns` calls: `self._show_view()`.

4c. View switching:
```python
    OV_BAR = 10
    OV_GLYPHS = (("█", "green"), ("▒", "cyan"), ("▓", "yellow"), ("░", "bright_black"))

    def _show_view(self) -> None:
        self.query_one("#ov").display = self.view == "overview"
        self.query_one("#hgview").display = self.view == "hgs"
        (self.query_one("#overview") if self.view == "overview" else self.query_one("#hgs")).focus()

    def open_group(self, name: str) -> None:
        self.group = None if name == "ALL" else name
        self.view = "hgs"
        self.selected.clear()
        self._show_view()
        if not self.by_stage:
            self._set_banner("loading history…")
        self._fill_hgs(keep="")
        self.load_bg()

    def action_back(self) -> None:
        if self.view == "hgs":
            self.view = "overview"
            self._show_view()
```
Bindings: add `Binding("escape", "back", "overview")`, `Binding("c", "by_category", "category")`. Change the `f` handler:
```python
    def action_cycle_filter(self) -> None:
        if self.view == "overview":
            self.by = "family"
            self.load_bg()
            return
        self.filter = FILTERS[(FILTERS.index(self.filter) + 1) % len(FILTERS)]
        self._fill_hgs()

    def action_by_category(self) -> None:
        if self.view == "overview":
            self.by = "category"
            self.load_bg()
```
Opening a cell (spec: `←→` picks the stage column; `enter` opens that group AT that stage, filter
`failed`, cursor in the HG list). The overview table uses `cursor_type="cell"` (change it in
`compose`), so `enter` emits `CellSelected`; columns 0–1 are group / HG count, column `2 + i` is
`core.STAGES[i]`:
```python
    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        if event.data_table.id != "overview" or self.view != "overview":
            return
        col = event.coordinate.column
        stage = core.STAGES[col - 2] if col >= 2 else None
        self.open_group(event.cell_key.row_key.value, stage)
```
and `open_group(name, stage=None)`: when `stage` is given and applicable, set `self.stage = stage`
and move the `#stages` cursor to it; always set `self.filter = "failed"`; focus `#hgs` (already in
`_show_view`). `_overview_footer` is driven by `on_data_table_cell_highlighted` for the overview
(the row is `event.coordinate.row`), instead of `row_highlighted`; `_key_at_cursor` already works on
the cursor row for a cell cursor. Overview cursor restore after refill uses
`t.move_cursor(row=…, column=t.cursor_column)` so the stage column is kept too.
The `c`/`f` switch must show the new grouping immediately (the tests only `await pilot.pause()`), so both actions regroup synchronously from the inputs of the last collect, then refresh in the background. Keep `self._ov_inputs = (exp, done, lv, known)` (set in `_apply`) and replace the two `self.load_bg()` calls above by `self._regroup()`:
```python
    def _regroup(self) -> None:
        exp, done, lv, _known = self._ov_inputs
        rows, _k = model.group_rows(self.cfg, exp, self.by, done, lv)   # no subprocess
        self._fill_overview(rows)
        self.load_bg()
```
`self._ov_inputs` starts as `(set(), {}, {}, True)` in `__init__` so `_regroup` before the first load is harmless (it fills ALL only). ⚠ `group_rows` with an empty `done` dict must not KeyError: guard with `done.get(st, set())` in Task 1's code if needed, and keep Task 1's tests passing.

4d. Collect — overview always, HG data only in the HG view, the expected set ONCE:
```python
    def _collect(self) -> dict:
        exp = core.expected(self.cfg)
        done_map = core.report_status.done_by_stage(str(self.cfg.outdir), exp)
        lv = model.live(exp)
        known = lv is not None
        lv = lv or {}
        ov_rows, _k = model.group_rows(self.cfg, exp, self.by, done_map, lv)
        snap = dict(ov_rows=ov_rows, ov_inputs=(exp, done_map, lv, known), known=known,
                    when=datetime.now(), hg=None)
        if self.view == "hgs":
            for hg in exp:                       # FASTAs are read here, off the UI thread, once
                if not self.nseq.get(hg):
                    self.nseq[hg] = core.nseq(self.cfg, hg)
            stages, _k2, _d = model.stage_rows(self.cfg, exp)
            atts = history.attempts(self.cfg)
            by_stage = {st: (model.hg_rows(self.cfg, st, exp, atts, done_map, lv)
                             if core.applicable(self.cfg, st) else [])
                        for st in core.STAGES}
            arrays, sacct_known = model.array_rows()
            snap["hg"] = dict(stages=stages, atts=atts, by_stage=by_stage, arrays=arrays,
                              sacct_known=sacct_known)
        return snap
```
⚠ `model.stage_rows` calls `live()` itself; if that second squeue call matters, leave it (it is cheap); do NOT change `stage_rows`' signature (the CLI uses it).

4e. `_apply(snap)`: always `self._ov_inputs = snap["ov_inputs"]; self._fill_overview(snap["ov_rows"])`; then, only if `snap["hg"]` is not None, run the existing body on `snap["hg"]` (atts, by_stage, stage table, arrays, `_fill_hgs`). Banner: build as before (squeue / sacct notes, sacct only when `snap["hg"]`), store in `self._banner_text`, plus "loading history…" while `self.view == "hgs"` and `not self.by_stage`. Use a helper:
```python
    def _set_banner(self, text: str) -> None:
        self._banner_text = text
        self.query_one("#banner", Static).update(text)
```

4f. `_fill_overview(rows)`:
```python
    def _fill_overview(self, rows: list) -> None:
        self.ov_rows = rows
        t = self.query_one("#overview", DataTable)
        keep = self._key_at_cursor(t)
        if not t.columns:
            t.add_columns("group", "HGs", *[s for s in core.STAGES])
        t.clear()
        for r in rows:
            cells = []
            for st in core.STAGES:
                c = r.per_stage.get(st)
                if c is None:
                    cells.append("n/a")
                    continue
                n = model.bar_segments(c, self.OV_BAR)
                cells.append("".join(f"[{fg}]{ch * k}[/]" for (ch, fg), k in zip(self.OV_GLYPHS, n) if k))
            t.add_row(r.group, str(r.total), *cells, key=r.group)
        keys = [r.group for r in rows]
        t.move_cursor(row=keys.index(keep) if keep in keys else 0)
        self._overview_footer()

    def _overview_footer(self) -> None:
        key = self._key_at_cursor(self.query_one("#overview", DataTable))
        r = next((x for x in self.ov_rows if x.group == key), None)
        if r is None:
            return
        parts = [f"{st} {c[0]}/{c[1]}/{c[2]}/{c[3]}" for st, c in r.per_stage.items() if c]
        self.query_one("#ovfoot", Static).update(
            f"[b]{r.group}[/] {r.total} HGs · done/running/ready/blocked: " + " · ".join(parts)
            + "\n█ done ▒ running ▓ ready/failed ░ blocked · enter: open · c/f: category/family")
```
In `on_data_table_row_highlighted`, add a branch for `t.id == "overview"` → `self._overview_footer()` (after the stale-highlight guard).

4g. `visible()` and the group filter:
```python
    def visible(self) -> list:
        rows = [r for r in self.rows if r.state == self.filter]
        if self.group is not None:
            rows = [r for r in rows if model.group_key(r.hg, self.by) == self.group]
        return rows
```
`action_select_all` already uses `visible()`; `action_resubmit` uses `self.selected`, which only ever holds visible HGs.

4h. README: replace the first paragraph of `## phylo tui` with the overview description (rows per category, `f`/`c`, `enter` opens the HG panels for that row, `esc` back, history read only there).

- [ ] **Step 5: Run both suites** — Expected: 180 passed on both (174 + 6), output clean.

- [ ] **Step 6: Commit** — `phylocli/tui.py`, `phylocli/tests/test_tui.py`, `phylocli/README.md`; message `phylocli tui: overview by category/family as the first view; HG view per group; history only in the HG view`.
