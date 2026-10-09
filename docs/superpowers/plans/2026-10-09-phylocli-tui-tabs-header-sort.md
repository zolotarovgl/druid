# phylocli TUI Jobs/Results tabs, header sorting, coverage colours, overview numbers, spinner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every listed TUI table gets a header cursor (`↑` on row 1 → header, `←/→`, `enter`/`s` sorts with `▲`/`▼`); the first screen gets a **Results** tab next to **Jobs** (`tab` switches), fed by one cached read of every HG's POSSVM output that the Results window reuses; the species pane is coloured by coverage; overview cells show `<done>/<total>` left of a 6-cell bar; a braille spinner turns while history / Results data load. Two Results-window cursor fixes from the Part C review ride along.

**Architecture:** One `SortTable(DataTable)` subclass in `tui.py` owns header mode, its sort state (`sort = (column name, reversed)`) and its header labels; the app orders rows in its existing fill functions through one pure helper `sort_rows(rows, sort, keys)` and is told of a new sort by a callback. The overview's `s` *is* the overview table's header sort (`ov_sort` becomes a read-only property over it — one state, not two). The Results tab is a second `SortTable` (`#rtab`) on the first screen, filled from `model.og_group_rows` (pure) over `self._og_cache`, which a `group="rtab"` worker fills with one `model.group_ogs` call over all expected HGs; `_load_results` takes that cache and skips `group_ogs` when it covers the group and source. The spinner is Part G's `#status` line turned into a `Spinner(Static)`, driven by Part G's `_update_status()`, which looks at what the current view waits for.

**Tech Stack:** Python ≥ 3.9, Textual 8.2.8 (optional), Rich, pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-phylocli-tui-results-tab-header-sort-design.md` — Parts A (tabs), B (header sorting), D (coverage colours), E (overview numbers), F (spinner). **Part C** (`/` per pane) landed as `fa7921b` + `d3c3d0a`; **Part G** (top strip with logo, key help and status line; warnings as notifications) landed separately as `b313b1d` + `6f04984` and is **not** in this plan. The two "deferred fixes" from the Part C review (coordinator, 09/10/2026) are Task 3.

**Repo / branch:** worktree `~/Documents/projects/phylogenies/phylocli-wt`, branch `phylocli`, **HEAD `6f04984`** (312 tests). Landed and relied on: Part C (`fa7921b`, `d3c3d0a`: `_flt`, `_refilter`, `_fill_res`, `_tcol` test helper) and Part G (`b313b1d`, `6f04984`): a top strip `Horizontal(id="strip")` in every view with `#logo`, `#help` (per-view key help from `_help_for(view)`, refreshed by `_update_help()`, called at the end of `_show_view`) and a one-line `#status` (`_update_status()`, text in `self._status`; `_hist_loading` drives "loading history…"); no banner; warnings via `_notify_once`; the overview and Results footers carry status only, no key legend. `#overview` and `#ovfoot` sit in `Vertical(id="ov")`. **Locate code by function name and by the quoted text, never by line number.** `git add` only the files a task lists; never revert someone else's change.

**Verified while writing (09/10/2026):**
- Prototype on Textual 8.2.8 (python 3.10 and the py39 venv): overriding `action_cursor_up/down/left/right` and `action_select_cursor` in a `DataTable` subclass intercepts `↑ ↓ ← →` and `enter` (the DataTable's own BINDINGS name these actions); a widget-level `Binding("s", …)` wins over the app's `s`, and raising `textual.actions.SkipAction` passes it on to the app binding; assigning `column.label = Text(…, style="reverse")` then `table._clear_caches(); table.refresh()` re-renders the header (checked via `render_line(0)`: the header cell's segment has `reverse`, `▼` is drawn); `clear()` + `add_row()` keep relabelled headers; toggling `show_cursor` is safe; the Screen's `tab` binding calls `app.action_focus_next`, so overriding that on the App switches tabs without touching the hgs/Results panes' `tab`.
- The whole plan (Tasks 1–6) was applied to a scratch copy of `d3c3d0a` (336 = 309 + 27), then rebased onto `6f04984` (Part G's strip) with the Task 4 help/footer and Task 6 status-line changes written below; both suites passed there: **339 = 312 + 27** (python 3.10 and py39, 09/10/2026).

## File Structure

| file | change | responsibility |
|---|---|---|
| `phylocli/tui.py` | modify | `SortCol`, `sort_arrow`, `sort_rows`, `SortTable`, column specs + sort keys per table, `rt_order`, Results tab (tab bar, worker, cache, footer), `coverage_style`, `species_text`, `ov_cell`, `Spinner` (as `#status`), `_update_status` Results-tab branch, `_help_for` Results-tab help |
| `phylocli/model.py` | append | `OGGroupRow`, `og_group_rows` (pure; no Textual) |
| `phylocli/tests/test_tui.py` | append (+1 line changed, +1 test body changed) | pilot tests per task |
| `phylocli/tests/test_model.py` | append | `og_group_rows` |

## Global Constraints

- CLI output text and exit codes of every `phylo` command stay byte-identical. Existing tests stay unmodified **except one** (required by Part B): `test_tui.py::test_s_on_group_and_hgs_columns` — `"Overview · sort: group ▼"` → `"Overview · sort: group ▲"` (Task 1): the arrow now shows the real direction (▼ descending, ▲ ascending) so the title agrees with the new header arrow; a name sort starts ascending. Stage/HGs titles (`tree ▼` / `tree ▲`, `search ▼`) are unchanged. Part G's tests (`test_strip_with_logo_and_help_is_in_every_view`, `test_open_group_before_hg_data_shows_loading` reading `_status` / `#status`) pass unchanged: Task 6 keeps `_status` as the plain text and puts the spinner glyph only in the widget.
- Python 3.9-safe (`from __future__ import annotations`; no `match`; no `X | Y` outside string annotations; `SortCol` is a `collections.namedtuple`, not a `typing.NamedTuple`).
- Textual is imported only in `tui.py`. `model.og_group_rows` is pure.
- No file or SLURM access on a key press (`↑ ↓ ← → enter s h tab shift+tab c f p o esc`, typing in the filter box). File reads only in workers: `load_bg` (default group), `_load_results` (`group="results"`), `_load_rtab` (new, `group="rtab"`), each following the `_collect`/`_apply` pattern (snapshot dict, `call_from_thread`, exceptions never escape, a generation counter drops superseded snapshots).
- Sort state is keyed by **column name**, never by index; a table keeps it across refills, regrouping, unit changes (`#hgs` family/HG) and source switches. Numbers sort descending first, text ascending first; ties keep the incoming order (stable sort). `ALL` stays pinned first on both first-screen tabs. One sorted column per table.
- `ov_rows` keeps its meaning (rows as computed by `model.group_rows`); `ov_shown` is the displayed order. `ov_sort` stays readable (tests read it) but is a property over `#overview`'s `sort`.
- Test commands (both must pass, output clean):
  `python3 -m pytest phylocli/tests -q -p no:cacheprovider` and
  `/tmp/claude-1000/-home-grygoriyzolotarov-Documents-projects-phylogenies/3dad6ea4-c859-4fe6-b319-93a358944ac8/scratchpad/py39/bin/python -m pytest phylocli/tests -q -p no:cacheprovider`.
  Record **N0 = the passed count before you start each task**; each task states its delta: Task 1 +5, Task 2 +4, Task 3 +2, Task 4 +8, Task 5 +5, Task 6 +3 (**+27**: 339 from `6f04984`'s 312 if nothing else lands).
- Commit on `phylocli`, message ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Edit with the Edit/Write tools only, never sed or python string-replace. Dates in docs `dd/mm/yyyy`.

## Review Focus

1. **`↑` on row 1 used to do nothing; now it enters the header** — every place that presses `up` near the top (selection in `2 HGs`, the Results panes) must still act on the row under the cursor once `↓` is pressed, and `space`/`a` in header mode must not crash → Task 2 `test_hgs_pane_header_sort_skips_mark_and_survives_refresh_and_unit` (`down`, `space` selects the first sorted row); the existing `test_key_presses_run_no_slurm` (`down`, `up`, `space`, `a` on a one-row table) passes unchanged.
2. **Sorting / filtering while a Results load is in flight** — `res_rows` is `[]` then; redrawing `#res` would empty it and lose the cursor's HG when the load lands → Task 3 `test_results_filter_during_load_keeps_cursor` (the guard sits in `_fill_res`, so a header sort during the load is covered by the same code path).
3. **The Results tab before the first refresh** — `_ov_inputs[0]` is empty until `load_bg` lands; a read started then would cache zero HGs and the tab would show zeros until `R` → Task 4 `test_results_tab_waits_for_first_refresh_and_shows_progress` (no read on `tab`, the read starts from `_apply`).
4. **Header mode and typing** — header mode must never swallow keys meant for the `/` box (`s`, `q`, `R`, `p`) → Task 2 `test_header_mode_never_captures_filter_typing`.
5. **Unreadable files on the Results tab** — a broken `ortholog_groups.csv` counts as "with output" but adds no OGs, and the footer names how many → Task 4 `test_results_tab_counts_unreadable_hgs`.

---

### Task 1: `SortTable` — header cursor and sort, on the overview (Jobs tab)

**Files:**
- Modify: `phylocli/tui.py` (imports; new module-level block before `class PhyloApp`; `PhyloApp.__init__`, `compose`, `on_mount`, `_fill_overview`, `_ov_title`, `action_sort`)
- Test: `phylocli/tests/test_tui.py` (append; one assert changed in `test_s_on_group_and_hgs_columns`)

**Interfaces:**
- Consumes: `OV_COLUMNS`, `OV_TOP`, `OV_SEP`, `ov_column(stage)`, `stage_at_column(col)`, `ov_order(rows, sort, hide)` (unchanged), `PhyloApp._fill_overview(rows)`, `_key_at_cursor(t)`.
- Produces:
  - `SortCol = namedtuple("SortCol", "name label numeric", defaults=(False,))` — `name: str | None` (None = not selectable), `label: str` (may hold `"\n"`), `numeric: bool`
  - `sort_arrow(numeric: bool, rev: bool) -> str` — `"▼"` if `numeric != rev` else `"▲"`
  - `sort_rows(rows: list, sort: tuple | None, keys: dict[str, tuple[callable, bool]]) -> list`
  - `OV_COLS: list[SortCol]` — `group`, `HGs` (numeric), then one per `OV_COLUMNS` entry (stage name, numeric; `None` for `│`)
  - `class SortTable(DataTable)` — attributes `cols: list[SortCol]`, `sort: tuple | None`, `header: bool`, `hcol: int`, `on_sort: callable(table) | None`; methods `set_cols(cols)`, `relabel()`, `sort_by(i: int)`, `enter_header()`, `leave_header(to_row=True)`
  - `PhyloApp.ov_sort` (read-only property = `#overview`'s `sort`), `PhyloApp._resorted(t: SortTable)` (dispatch by `t.id`; later tasks add branches)

- [ ] **Step 1: Write the failing tests** (append to `phylocli/tests/test_tui.py`; they reuse `_sorted_fixture`, `_shown`, `_pair`, `_to_col`, `_family_overview`, `_key` from the overview sort/hide section):

```python
# ---- header sorting ---------------------------------------------------------------------------
def _heads(app, wid):
    """Header labels of a table as shown (the overview's are two-row: 'step2 ·\\nalign')."""
    return [c.label.plain for c in app.query_one(wid).ordered_columns]


def _hcur(app, wid):
    """Index of the reversed header label (the header cursor), None outside header mode."""
    hits = [i for i, c in enumerate(app.query_one(wid).ordered_columns) if "reverse" in str(c.label.style)]
    return hits[0] if hits else None


def test_sort_rows_and_arrow():
    keys = {"n": (lambda r: r[1], True), "name": (lambda r: r[0], False)}
    rows = [("b", 1), ("a", 3), ("c", 1)]
    assert tui.sort_rows(rows, ("n", False), keys) == [("a", 3), ("b", 1), ("c", 1)]   # ties keep order
    assert tui.sort_rows(rows, ("n", True), keys) == [("b", 1), ("c", 1), ("a", 3)]
    assert tui.sort_rows(rows, ("name", False), keys) == [("a", 3), ("b", 1), ("c", 1)]
    assert tui.sort_rows(rows, None, keys) == rows and tui.sort_rows(rows, ("x", False), keys) == rows
    assert (tui.sort_arrow(True, False), tui.sort_arrow(True, True)) == ("▼", "▲")
    assert (tui.sort_arrow(False, False), tui.sort_arrow(False, True)) == ("▲", "▼")


def test_up_on_first_row_enters_overview_header_and_down_leaves(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            ov = app.query_one("#overview")
            _to_col(app, "tree", row=1)
            await _key(pilot, "up")
            assert not ov.header and ov.cursor_row == 0
            await _key(pilot, "up")                                  # row 0: into the header
            assert ov.header and _hcur(app, "#overview") == tui.ov_column("tree")
            await _key(pilot, "right")
            assert _hcur(app, "#overview") == tui.ov_column("tree") + 1
            await _key(pilot, "down")                                # back to the first row
            assert not ov.header and _hcur(app, "#overview") is None
            assert ov.cursor_row == 0 and ov.cursor_column == tui.ov_column("tree") + 1
    _run(go())


def test_header_enter_and_s_sort_with_arrow_and_same_state_as_cell_s(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            ov = app.query_one("#overview")
            _to_col(app, "tree")
            await _key(pilot, "up", "enter")                         # header: sort, never open
            assert app.view == "overview" and ov.header
            assert app.ov_sort == ("tree", False) and _pair(app) == ["tfs.C_x", "tfs.A"]
            assert _heads(app, "#overview")[tui.ov_column("tree")] == "HGs\ntree ▼"
            await _key(pilot, "s")                                   # s in the header: reverse
            assert app.ov_sort == ("tree", True) and _pair(app) == ["tfs.A", "tfs.C_x"]
            assert _heads(app, "#overview")[tui.ov_column("tree")] == "HGs\ntree ▲"
            await _key(pilot, "down", "s")                           # s on a cell: the same sort
            assert app.ov_sort == ("tree", False) and ov.cursor_row == 0
            assert app.query_one("#overview").border_title == "Overview · sort: tree ▼"
            _to_col(app, "group")
            await _key(pilot, "up", "enter")                         # text: ascending first
            assert app.ov_sort == ("group", False) and _heads(app, "#overview")[0] == "\ngroup ▲"
            assert _heads(app, "#overview")[tui.ov_column("tree")] == "HGs\ntree"   # one arrow
            assert _shown(app)[0] == "ALL"                           # ALL stays pinned
    _run(go())


def test_header_skips_separator_and_sort_survives_refresh(cli):
    _sorted_fixture()

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            ov = app.query_one("#overview")
            sep = tui.ov_column("align") - 1
            ov.move_cursor(row=0, column=sep - 1)
            await pilot.pause()
            await _key(pilot, "up", "right")                         # cluster -> align, not │
            assert _hcur(app, "#overview") == tui.ov_column("align")
            await _key(pilot, "left")
            assert _hcur(app, "#overview") == sep - 1
            ov.move_cursor(row=0, column=sep)
            await _key(pilot, "down")
            ov.move_cursor(row=0, column=sep)
            await pilot.pause()
            await _key(pilot, "up")                                  # from │: next column right
            assert _hcur(app, "#overview") == tui.ov_column("align")
            await _key(pilot, "enter")
            app.load_now()
            await pilot.pause()
            assert app.ov_sort == ("align", False)
            assert _heads(app, "#overview")[tui.ov_column("align")].endswith("align ▼")
            assert _hcur(app, "#overview") == tui.ov_column("align")   # still in header mode
            await _key(pilot, "c")                                   # regroup: sort kept
            assert app.ov_sort == ("align", False) and _shown(app)[0] == "ALL"
    _run(go())


def test_header_keys_touch_no_files_or_slurm(cli, monkeypatch):
    _sorted_fixture()

    def boom(*a, **k):
        raise AssertionError("file or SLURM access on a header key")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _family_overview(app, pilot)
            await app.workers.wait_for_complete()
            monkeypatch.setattr(core, "ready_set", boom)
            monkeypatch.setattr(core.report_status, "done_by_stage", boom)
            monkeypatch.setattr(core.report_status, "nonempty_files", boom)
            monkeypatch.setattr(tui.model, "_slurm", boom)
            _to_col(app, "tree")
            await _key(pilot, "up", "left", "right", "enter", "s", "down")
            assert app.ov_sort == ("tree", True)
    _run(go())
```

Also change one line in the existing `test_s_on_group_and_hgs_columns` (spec change, see Global Constraints):

```python
            assert app.query_one("#overview").border_title == "Overview · sort: group ▲"
```
(was `… group ▼`).

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider -k "sort_rows or header or s_on_group"` — Expected: FAIL (`AttributeError: module 'phylocli.tui' has no attribute 'sort_rows'`, `'DataTable' object has no attribute 'header'`, and `test_s_on_group_and_hgs_columns` on `▲`).

- [ ] **Step 3: Implement.**

Imports (top of `tui.py`): add `from rich.cells import cell_len` after `import yaml`, and `from textual.actions import SkipAction` after `from textual import work`.

Insert this block **immediately before `class PhyloApp(App):`** (after `ov_order`):

```python
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


OV_COLS = [SortCol("group", "\ngroup"), SortCol("HGs", "\nHGs", True),
           *(SortCol(None, f"{OV_SEP}\n{OV_SEP}") if st is None
             else SortCol(st, f"{OV_TOP.get(st, '')}\n{st}", True) for st in OV_COLUMNS)]


class SortTable(DataTable):
    """A DataTable with a header cursor (Grygoriy, 09/10/2026): ↑ on the first row enters the
    header, ←/→ move between column names (skipping unnamed columns), enter or s sorts by that
    column (again: reversed), ↓ returns to the first row.  Outside the header, s on a cell table
    sorts by the cursor's column (the overview's s), on a row table it falls through.
    The table owns its sort (`sort` = (column name, reversed) or None, kept across refills) and
    its header labels (▲/▼ after the sorted column, the header cursor reversed); the app orders
    the rows in its fill functions and is told of a new sort by `on_sort(table)`.
    Textual 8.2.8's DataTable has no header cursor: the cursor actions are overridden here, and
    `_clear_caches` (private) is the only way to re-render a relabelled header."""
    BINDINGS = [Binding("s", "sort_here", "sort", show=False)]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cols: list = []
        self.sort: "tuple | None" = None
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
        text = c.label
        if self.sort is not None and c.name is not None and self.sort[0] == c.name:
            text += " " + sort_arrow(c.numeric, self.sort[1])
        return Text(text, style="reverse" if self.header and i == self.hcol else "")

    def relabel(self) -> None:
        for i, col in enumerate(self.ordered_columns[:len(self.cols)]):
            col.label = self._label(i)
            col.content_width = max(col.content_width,
                                    *(cell_len(x) for x in col.label.plain.split("\n")))
        self._clear_caches()
        self._require_update_dimensions = True
        self.refresh()

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

    def leave_header(self, to_row: bool = True) -> None:
        self.header = False
        self.show_cursor = True
        if to_row and self.row_count:
            self.move_cursor(row=0, column=self.hcol if self.cursor_type == "cell" else None)
        self.relabel()

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
        same = self.sort is not None and self.sort[0] == name
        self.sort = (name, not self.sort[1] if same else False)
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
```

In `PhyloApp.__init__`, delete the line `self.ov_sort: "tuple | None" = None     # (column name, reversed); s` (it becomes a property; assigning it would raise).

In `compose`, the overview table line (inside `Vertical(id="ov")`) becomes:

```python
            yield SortTable(id="overview", cursor_type="cell", header_height=2)   # step1/step2 header
```

In `on_mount`, right after the `#stages` `add_columns(...)` line, add:

```python
        self.query_one("#overview", SortTable).set_cols(OV_COLS)
        for t in self.query(SortTable):          # a header sort reorders that table, in memory
            t.on_sort = self._resorted
```

In `_fill_overview`, delete the lazy column creation (the columns now come from `OV_COLS` at mount):

```python
        if not t.columns:
            t.add_columns(Text("\ngroup"), Text("\nHGs"),
                          *(Text(f"{OV_SEP}\n{OV_SEP}") if st is None
                            else Text(f"{OV_TOP.get(st, '')}\n{st}") for st in OV_COLUMNS))
```

In `_ov_title`, replace `parts.append(f"sort: {self.ov_sort[0]} {'▲' if self.ov_sort[1] else '▼'}")` with:

```python
            col, rev = self.ov_sort                # the same arrow as the column header
            parts.append(f"sort: {col} {sort_arrow(col != 'group', rev)}")
```

Replace the whole `action_sort` method with:

```python
    @property
    def ov_sort(self) -> "tuple | None":
        """The overview's sort = its table's header sort: one state for s and the header."""
        return self.query_one("#overview", SortTable).sort

    def action_sort(self) -> None:
        """s with the overview table not focused (focused, the table's own s handles it)."""
        if self.view == "overview":
            t = self.query_one("#overview", SortTable)
            t.sort_by(t.cursor_column)           # no-op on the │ separator

    def _resorted(self, t: "SortTable") -> None:
        """A table's sort changed (header enter / s, or s on a cell): reorder it in memory."""
        if t.id == "overview":
            self._fill_overview(self.ov_rows)
```

`action_hide`, `_ov_column`, `ov_order` and `check_action` stay as they are (the existing `s`/`h` tests keep passing: `ov_sort` still reads `("tree", False)`).

- [ ] **Step 4: Run** both suites — Expected: N0 + 5 passed (the changed assert passes).

- [ ] **Step 5: Commit**

```bash
git add phylocli/tui.py phylocli/tests/test_tui.py
git commit -m "tui: header sorting (SortTable) on the overview; s on a cell is the same sort; ▲/▼ show the real direction

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: header sorting in `2 HGs` and the Results window panes

**Files:**
- Modify: `phylocli/tui.py` (`import math`; module-level column specs/keys before `class SortTable`; `compose`; `on_mount`; `_set_units`; `visible`; new `_hg_keys`; `_fill_res`; `_fill_ogs`; `_fill_members`; `_resorted`)
- Test: `phylocli/tests/test_tui.py` (append)

**Interfaces:**
- Consumes: Task 1's `SortCol`, `sort_rows`, `SortTable`, `_resorted`; `model.hg_sort_key`, `model.bump_reason`, `model.parse_duration_min`, `core.parse_mem_mb`; Part C's `_flt`, `_tcol(app, table, c=0)` test helper.
- Produces:
  - `hg_cols(unit: str) -> list[SortCol]` — names `None` (mark, not sortable), `id`, `n`, `state`, `last`, `req`, `used`; labels follow the unit (`family`/`HGs` or `HG`/`seqs`)
  - `RES_COLS`, `RES_KEYS` (names `hg`, `ogs`, `genes`, `zero`), `OG_COLS`, `OG_KEYS` (`og`, `genes`, `spp`, `support`, `name`), `MEM_COLS`, `MEM_KEYS` (`gene`, `sp`, `ref`, `sup`; keys take `(index, Member)` pairs)
  - `_mem_time_key(mem: str, time: str) -> tuple[int, int]`, `_lead_float(s: str) -> float`
  - `PhyloApp._hg_keys() -> dict`; `PhyloApp._fill_ogs(keep: str | None = None)` (cursor to OG `keep` when shown)
  - `#hgs`, `#res`, `#ogs`, `#members` are `SortTable`s; `#stages` and `#arrays` stay plain `DataTable`s (spec: not sorted).

- [ ] **Step 1: Write the failing tests** (append):

```python
def test_hgs_pane_header_sort_skips_mark_and_survives_refresh_and_unit(cli, monkeypatch):
    app = _failed_app(cli, monkeypatch)
    app.filter = "actionable"                    # tfs.A.HG11 ready (3 seqs), tfs.C_x.HG1 failed (600)

    async def go():
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            t = app.query_one("#hgs")
            t.focus()
            t.move_cursor(row=0)
            await pilot.pause()
            await _key(pilot, "up")
            assert t.header and _hcur(app, "#hgs") == 1             # HG: the mark is skipped
            await _key(pilot, "left")
            assert _hcur(app, "#hgs") == 1
            await _key(pilot, "right", "enter")                      # seqs: numbers descending
            assert [r.hg for r in app.visible()] == ["tfs.C_x.HG1", "tfs.A.HG11"]
            assert _heads(app, "#hgs")[2] == "seqs ▼"
            await _key(pilot, "enter")
            assert [r.hg for r in app.visible()] == ["tfs.A.HG11", "tfs.C_x.HG1"]
            assert _heads(app, "#hgs")[2] == "seqs ▲"
            await _key(pilot, "down", "space")                       # rows again: row 0 selected
            assert not t.header and app.selected == {"tfs.A.HG11"}
            app.load_now()
            await pilot.pause()
            assert [r.hg for r in app.visible()] == ["tfs.A.HG11", "tfs.C_x.HG1"]
            app.open_group("ALL", "search")                          # family unit: same column
            await pilot.pause()
            assert _heads(app, "#hgs")[1:3] == ["family", "HGs ▲"]
    _run(go())


def test_results_panes_header_sort_independently(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            await _key(pilot, "up", "right", "enter", "enter")      # Results: OGs ascending
            assert _tcol(app, "#res") == ["tfs.A.HG11", "tfs.A.HG1"]
            assert _heads(app, "#res") == ["HG", "OGs ▲", "genes", "⚠"]
            await _key(pilot, "down")
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG11"
            await _key(pilot, "up")                                  # cursor back on HG1 ...
            app.query_one("#res").move_cursor(row=1)
            await pilot.pause()
            assert app.query_one("#ogs").border_title.startswith("OGs · tfs.A.HG1 ")
            await _key(pilot, "tab", "up", "right", "right", "right", "enter")   # OGs: support
            assert _tcol(app, "#ogs") == ["HG1.0", "HG1.1"]
            assert _heads(app, "#ogs")[3] == "support ▼"
            await _key(pilot, "enter")                               # reversed: cursor stays on OG
            assert _tcol(app, "#ogs") == ["HG1.1", "HG1.0"]
            assert app._key_at_cursor(app.query_one("#ogs")) == "tfs.A.HG1.0"
            assert app.query_one("#members").border_title == "members · HG1.0 T/Tbx19"
            await _key(pilot, "down")                                # first row: HG1.1
            assert app.query_one("#members").border_title == "members · HG1.1 like:Eomes/Tbr1"
            await _key(pilot, "tab", "up", "right", "enter")        # members: sp, text ascending
            assert _member_genes(app) == ["Hsap_ENSP2", "Nvec_v1_g3"]
            await _key(pilot, "enter")
            assert _member_genes(app) == ["Nvec_v1_g3", "Hsap_ENSP2"]
            assert _heads(app, "#res")[1] == "OGs ▲"                 # each pane its own sort
            assert app.query_one("#res").sort == ("ogs", True)
            assert app.query_one("#ogs").sort == ("support", True)
            assert app.query_one("#members").sort == ("sp", True)
            await pilot.press("p")                                   # new source: sorts kept
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_source == "possvm_prev" and _heads(app, "#res")[1] == "OGs ▲"
    _run(go())


def test_header_mode_never_captures_filter_typing(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            await _key(pilot, "tab", "tab", "up")                    # members header mode
            m = app.query_one("#members")
            assert m.header
            await _key(pilot, "slash", "s", "q", "R", "p")           # all text for the box
            inp = app.query_one("#memfilter")
            assert inp.value == "sqRp" and app.focused is inp
            assert m.sort is None and not m.header and app.view == "results"
            assert app.res_source == "possvm"
    _run(go())


def test_header_sort_on_empty_results_pane(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "cal")                   # a group with no HGs
            assert app.query_one("#res").row_count == 0
            await _key(pilot, "up", "enter", "down")
            assert app.query_one("#res").sort == ("hg", False) and app.view == "results"
    _run(go())
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider -k "hgs_pane_header or results_panes_header or never_captures or empty_results_pane"` — Expected: FAIL (`'DataTable' object has no attribute 'header'` on `#hgs` / `#res` / `#members`).

- [ ] **Step 3: Implement.**

Add `import math` after `import collections`.

Insert immediately before `class SortTable(DataTable):`:

```python
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
    """98.2 of '98.2/97.0'; -inf for NA / empty (sorts last when descending)."""
    try:
        return float(s.split("/", 1)[0])
    except ValueError:
        return -math.inf


RES_COLS = [SortCol("hg", "HG"), SortCol("ogs", "OGs", True), SortCol("genes", "genes", True),
            SortCol("zero", "⚠", True)]
RES_KEYS = {"hg": (lambda r: model.hg_sort_key(r.hg), False),     # an unreadable HG: -1
            "ogs": (lambda r: -1 if r.error else len(r.ogs), True),
            "genes": (lambda r: -1 if r.error else sum(len(o.genes) for o in r.ogs), True),
            "zero": (lambda r: -1 if r.error else sum(1 for o in r.ogs if o.support == 0), True)}
# no reference-ortholog columns in OGs: the reference is per gene (it differs within 19 % of
# OGs) and is shown per row in `members` (Grygoriy, 09/10/2026)
OG_COLS = [SortCol("og", "OG"), SortCol("genes", "genes", True), SortCol("spp", "spp", True),
           SortCol("support", "support", True), SortCol("name", "name")]
OG_KEYS = {"og": (lambda o: int(o.id.rsplit(".", 1)[1]), False),
           "genes": (lambda o: len(o.genes), True),
           "spp": (lambda o: len({m.species for m in o.genes}), True),
           "support": (lambda o: -math.inf if o.support is None else o.support, True),
           "name": (lambda o: o.name.lower(), False)}
MEM_COLS = [SortCol("gene", "gene"), SortCol("sp", "sp"), SortCol("ref", "ref.orth"),
            SortCol("sup", "sup", True)]
MEM_KEYS = {"gene": (lambda p: p[1].gene, False), "sp": (lambda p: p[1].species, False),   # (i, Member)
            "ref": (lambda p: p[1].ref, False), "sup": (lambda p: _lead_float(p[1].ref_support), True)}
```

In `compose`, change the four tables to `SortTable` (keep ids, cursor types, positions):

```python
            yield SortTable(id="hgs", cursor_type="row")
```
```python
                yield SortTable(id="res", cursor_type="row")
                yield SortTable(id="ogs", cursor_type="row")
```
```python
                    yield SortTable(id="members", cursor_type="row")
```

In `on_mount`, replace the three `add_columns` lines for `#res`, `#ogs`, `#members` and the two-line comment between them with:

```python
        self.query_one("#res", SortTable).set_cols(RES_COLS)
        self.query_one("#ogs", SortTable).set_cols(OG_COLS)
        self.query_one("#members", SortTable).set_cols(MEM_COLS)
```
(The `for t in self.query(SortTable)` loop from Task 1 must stay **after** `compose` has yielded all tables — it is in `on_mount`, so it covers the four new ones too.)

In `_set_units`, replace

```python
        t = self.query_one("#hgs", DataTable)
        t.clear(columns=True)
        t.add_columns(" ", "family" if unit == "family" else "HG", "HGs" if unit == "family" else "seqs",
                      "state", "last", "req", "used")
```
with
```python
        self.query_one("#hgs", SortTable).set_cols(hg_cols(unit))   # sort kept (stable names)
```

In `visible`, replace the final `return rows` with the sorted return, and add `_hg_keys` right after `visible`:

```python
        return sort_rows(rows, self.query_one("#hgs", SortTable).sort, self._hg_keys())

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
```
(`_fill_hgs`, `_cursor_hg`, `action_select_all` all go through `visible()`, so table rows and `vis[t.cursor_row]` stay in the same order.)

In `_fill_res`, replace `rows = [r for r in self.res_rows if q in r.hg.lower()]` with:

```python
        rows = sort_rows([r for r in self.res_rows if q in r.hg.lower()], t.sort, RES_KEYS)
```

Replace `_fill_ogs`'s header and its loop/cursor lines so that it reads:

```python
    def _fill_ogs(self, keep: "str | None" = None) -> None:
        """OG table of the HG under the Results cursor (in memory), then its members/species.
        The cursor goes to OG `keep` when shown (a re-sort), else to the first row."""
        r = self._cur_res()
        t = self.query_one("#ogs", SortTable)
        t.clear()
        t.border_title = f"OGs · {r.hg if r else '–'} · {self.res_source or '…'}{self._ftag('ogs')}"
        q = self._flt["ogs"].lower()
        ogs = [o for o in r.ogs if q in o.id.lower() or q in o.name.lower()] if r else []
        ogs = sort_rows(ogs, t.sort, OG_KEYS)
        for og in ogs:
            sup = ("–" if og.support is None else "0.0 ⚠" if og.support == 0
                   else f"{og.support:.1f}")
            t.add_row(_short_og(og.id), str(len(og.genes)),
                      str(len({m.species for m in og.genes})), sup, escape(_trunc(og.name)),
                      key=og.id)
        keys = [o.id for o in ogs]
        if keys:
            t.move_cursor(row=keys.index(keep) if keep in keys else 0)
        self._show_og()
```

In `_fill_members`, use `SortTable` for the table lookup and sort the `(index, Member)` pairs (the row keys `f"{i}:{m.gene}"` stay unique):

```python
        t = self.query_one("#members", SortTable)
```
```python
        for i, m in sort_rows(list(enumerate(og.genes if og else [])), t.sort, MEM_KEYS):
```

Extend `_resorted`:

```python
        if t.id == "overview":
            self._fill_overview(self.ov_rows)
        elif t.id == "hgs":
            self._fill_hgs()                     # keeps the cursor on the same HG
        elif t.id == "res":
            self._fill_res(self._key_at_cursor(t))
        elif t.id == "ogs":
            self._fill_ogs(keep=self._key_at_cursor(t))
        elif t.id == "members":
            self._fill_members()
```

- [ ] **Step 4: Run** both suites — Expected: N0 + 4 passed. (Existing `test_hg_view_headers_follow_the_unit` still reads `["family", "HGs"]`: no arrow without a sort.)

- [ ] **Step 5: Commit**

```bash
git add phylocli/tui.py phylocli/tests/test_tui.py
git commit -m "tui: header sorting in 2 HGs and the Results window's Results / OGs / members panes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Results window cursor fixes (Part C review, deferred)

(a) `_fill_ogs` reset the OGs cursor to row 0 on every OGs filter keystroke and when a Results filter was refined; (b) filtering (or sorting) `Results` while a load is in flight redrew `#res` from the empty `res_rows`, so the cursor's HG was lost when the load landed.

**Files:**
- Modify: `phylocli/tui.py` (`_fill_ogs`, `_fill_res`)
- Test: `phylocli/tests/test_tui.py` (append)

**Interfaces:**
- Consumes: Task 2's `_fill_ogs(keep=None)`; Part C's `_refilter`, `_flt`, `on_data_table_row_highlighted` (calls `_fill_ogs()` on a `#res` highlight); `#resv.loading` (set by `_reload_results`, cleared by `_apply_results` before it calls `_fill_res`).
- Produces: `_fill_ogs(keep=None)` now defaults `keep` to the OG under the OGs cursor (an OG id contains its HG, so a different HG falls back to row 0); `_fill_res` is a no-op except for the title while `#resv` has `.loading`.

- [ ] **Step 1: Write the failing tests** (append):

```python
# ---- Results cursor fixes (Part C review) -----------------------------------------------------
def test_filters_keep_the_og_cursor_when_it_still_matches(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            ogs = app.query_one("#ogs")
            await _key(pilot, "tab", "down")                         # OGs: HG1.1
            assert app._key_at_cursor(ogs) == "tfs.A.HG1.1"
            await _key(pilot, "slash", "h", "g", "enter")           # both OGs match: kept
            assert _tcol(app, "#ogs") == ["HG1.0", "HG1.1"]
            assert app._key_at_cursor(ogs) == "tfs.A.HG1.1"
            await _key(pilot, "shift+tab", "slash", "h", "g", "1")  # refine Results /hg1 ...
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG1"
            assert app._key_at_cursor(ogs) == "tfs.A.HG1.1"          # ... same HG: OG kept
            await _key(pilot, "1")                                   # /hg11: another HG -> row 0
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG11"
            assert app._key_at_cursor(ogs) == "tfs.A.HG11.0"
    _run(go())


def test_results_filter_during_load_keeps_cursor(cli, monkeypatch):
    import threading
    write_results(_cfg())
    gate = threading.Event()
    gate.set()
    real = tui.model.read_ogs

    def gated(*a, **k):
        gate.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(tui.model, "read_ogs", gated)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            app.query_one("#res").move_cursor(row=1)                 # tfs.A.HG11
            await pilot.pause()
            gate.clear()
            await _key(pilot, "R")                                   # reload, held at the gate
            assert app.query_one("#resv").has_class("loading") and app.res_rows == []
            await _key(pilot, "slash", "h", "g", "1", "enter")      # filter while loading
            assert _tcol(app, "#res") == ["tfs.A.HG1", "tfs.A.HG11"]     # greyed rows stay
            assert app.query_one("#res").border_title == "Results · tfs · /hg1"
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert _tcol(app, "#res") == ["tfs.A.HG1", "tfs.A.HG11"]
            assert app._key_at_cursor(app.query_one("#res")) == "tfs.A.HG11"
    _run(go())
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider -k "keep_the_og_cursor or during_load_keeps"` — Expected: FAIL — `assert 'tfs.A.HG1.0' == 'tfs.A.HG1.1'` and `assert [] == ['tfs.A.HG1', 'tfs.A.HG11']` (both measured on the scratch copy).

- [ ] **Step 3: Implement.**

In `_fill_ogs`, replace the docstring and the lines up to `t.clear()` with:

```python
        """OG table of the HG under the Results cursor (in memory), then its members/species.
        The cursor stays on OG `keep` (default: the OG under the cursor now) when it is still
        shown, e.g. while typing an OGs or Results filter or after a re-sort; else row 0."""
        r = self._cur_res()
        t = self.query_one("#ogs", SortTable)
        if keep is None:
            keep = self._key_at_cursor(t)
        t.clear()
```

In `_fill_res`, insert right after `t = self.query_one("#res", DataTable)`:

```python
        if self.query_one("#resv").has_class("loading"):
            # rows not read yet (res_rows is []): redrawing now would empty the table and lose
            # the cursor's HG; the filter / sort apply when _apply_results lands
            self._set_res_title()
            return
```
(`_apply_results` removes `.loading` before it calls `_fill_res`, and takes `keep` from the still-drawn greyed rows.)

- [ ] **Step 4: Run** both suites — Expected: N0 + 2 passed.

- [ ] **Step 5: Commit**

```bash
git add phylocli/tui.py phylocli/tests/test_tui.py
git commit -m "tui Results: filters keep the OG cursor when it still matches; a Results filter during a load keeps the cursor's HG

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Jobs / Results tabs on the first screen (Part A)

**Files:**
- Modify: `phylocli/model.py` (append), `phylocli/tui.py` (`PANE_TITLES`; module-level `RT_COLS`, `RT_KEYS`, `rt_order` before `class SortTable`; CSS; `__init__`; `compose`; `on_mount`; `_apply`; `_show_view` + new tab/Results-tab methods; `_help_for`; `_fill_overview`; `_overview_footer`; `check_action`; `action_sort`; `_resorted`; `action_hide`; `on_data_table_cell_selected`; `on_data_table_cell_highlighted`; `action_refresh`; `action_open_results`; `_open_results`; `_reload_results`; `_load_results`; `action_toggle_source`)
- Test: `phylocli/tests/test_model.py` (append), `phylocli/tests/test_tui.py` (append)

**Interfaces:**
- Consumes: `model.group_ogs(cfg, hgs, source, progress=, cancelled=) -> (list[HGOgs], int)`, `model.default_source`, `model.group_key`, `model.hg_sort_key`; Task 1–2 `SortTable`, `SortCol`, `sort_rows`, `_resorted`; `_ov_inputs[0]` (expected HGs of the last snapshot), `ov_rows`, `by`.
- Produces:
  - `model.OGGroupRow(group, hgs, with_output, ogs, genes, zero, unreadable)`; `model.og_group_rows(groups: list[str], exp, by: str, rows: Iterable[HGOgs]) -> list[OGGroupRow]`
  - `tui.RT_COLS` (names = `OGGroupRow` fields `group hgs with_output ogs genes zero`), `RT_KEYS`, `rt_order(rows, sort, hide) -> list`
  - `PhyloApp.tab: "jobs" | "results"`, `rt_source`, `rt_hide`, `rt_rows`, `rt_shown`, `_og_cache: dict | None` = `{"source": str, "rows": {hg: HGOgs}, "hgs": frozenset}`, `_rt_gen`, `_rt_note`, `_rt_foot`, `_tab_text`, `_res_want`
  - methods `_set_tabbar`, `_switch_tab`, `action_focus_next`, `action_focus_previous`, `_rt_loading() -> bool`, `_maybe_load_rtab`, `_reload_rtab`, `_load_rtab(hgs, source, gen)` (worker, `group="rtab"`), `_rt_progress(gen, k, n)`, `_apply_rtab(snap)`, `_fill_rtab`, `_rt_footer`; `_open_results(group, by, focus=None, source=None)`; `_load_results(hgs, source, gen, cache=None)`

Decisions: `p` on the tab and `p` in the Results window are the same key with the same meaning, but each view keeps its own source; opening the window from the tab passes the tab's source, so the cache is reused. `R` anywhere drops the cache. A failed tab read caches an empty HG set, so the window then reads its group itself and the tab does not retry on every refresh (only `R`/`p` do).

- [ ] **Step 1: Write the failing tests.**

Append to `phylocli/tests/test_model.py`:

```python
def test_og_group_rows_sums_per_group(cli):
    cfg = _cfg()
    write_results(cfg)
    exp = {"tfs.A.HG1", "tfs.A.HG11", "tfs.C_x.HG1"}
    rows, missing = model.group_ogs(cfg, exp, "possvm")
    rows.append(model.HGOgs("tfs.C_x.HG1", [], "bad.csv:2: cannot parse row"))
    out = model.og_group_rows(["ALL", "tfs", "cal"], exp, "category", rows)
    assert [(r.group, r.hgs, r.with_output, r.ogs, r.genes, r.zero, r.unreadable) for r in out] == [
        ("ALL", 3, 3, 3, 7, 1, 1), ("tfs", 3, 3, 3, 7, 1, 1), ("cal", 0, 0, 0, 0, 0, 0)]
    fam = model.og_group_rows(["tfs.A", "tfs.C_x"], exp, "family", rows[:2])
    assert [(r.group, r.hgs, r.with_output, r.ogs) for r in fam] == [("tfs.A", 2, 2, 3),
                                                                     ("tfs.C_x", 1, 0, 0)]
```

Append to `phylocli/tests/test_tui.py` (fixture numbers: possvm has tfs.A.HG1 = 2 OGs / 5 genes / 1 support-0 OG and tfs.A.HG11 = 1 OG / 2 genes; possvm_prev has tfs.A.HG1 only = 1 OG / 2 genes; three expected HGs, all in `tfs`; `cal` and `slc` have families but no HGs):

```python
# ---- Results tab (first screen) ---------------------------------------------------------------
def _count_group_ogs(monkeypatch):
    calls = []
    real = tui.model.group_ogs

    def counted(cfg, hgs, source, **k):
        calls.append((len(list(hgs)), source))
        return real(cfg, hgs, source, **k)
    monkeypatch.setattr(tui.model, "group_ogs", counted)
    return calls


async def _results_tab(app, pilot):
    """First screen, after the first refresh -> tab -> wait for the one read."""
    app.load_now()
    await pilot.pause()
    await pilot.press("tab")
    await app.workers.wait_for_complete()
    await pilot.pause()


def _rt(app):
    return [(r.group, r.hgs, r.with_output, r.ogs, r.genes, r.zero) for r in app.rt_shown]


def test_tab_switches_jobs_and_results_tabs(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            assert app._tab_text == "[Jobs] │ Results" and app.focused is app.query_one("#overview")
            await pilot.press("tab")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.tab == "results" and app._tab_text == "Jobs │ [Results]"
            assert app.focused is app.query_one("#rtab") and not app.query_one("#overview").display
            assert [r.group for r in app.rt_shown] == [r.group for r in app.ov_rows]   # same groups
            assert _rt(app)[:2] == [("ALL", 3, 2, 3, 7, 1), ("tfs", 3, 2, 3, 7, 1)]
            assert _rt(app)[2][1:] == (0, 0, 0, 0, 0)
            assert app.query_one("#rtab").border_title == "Results · possvm"
            assert app.check_action("toggle_source", ()) and app.check_action("sort", ())
            await _key(pilot, "shift+tab")
            assert app.tab == "jobs" and app.focused is app.query_one("#overview")
            assert not app.check_action("toggle_source", ())
            await _key(pilot, "f", "tab")                            # by family: kept across tabs
            assert app.by == "family" and app.tab == "results"
            assert ("tfs.A", 2, 2, 3, 7, 1) in _rt(app) and ("tfs.C_x", 1, 0, 0, 0, 0) in _rt(app)
    _run(go())


def test_results_tab_reads_once_and_window_reuses_it(cli, monkeypatch):
    write_results(_cfg())
    calls = _count_group_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            assert calls == [(3, "possvm")]
            rt = app.query_one("#rtab")
            rt.move_cursor(row=[r.group for r in app.rt_shown].index("tfs"), column=3)
            await pilot.pause()
            await pilot.press("enter")                               # opens the Results window
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and app.res_group == "tfs"
            assert [r.hg for r in app.res_rows] == ["tfs.A.HG1", "tfs.A.HG11"]
            win = [_cells(app, "#res", i) for i in range(app.query_one("#res").row_count)]
            tab = next(r for r in app.rt_rows if r.group == "tfs")
            assert (tab.with_output, tab.hgs) == (len(app.res_rows), len(app.res_rows) + app.res_missing)
            assert (tab.ogs, tab.genes, tab.zero) == tuple(sum(int(c[i]) for c in win) for i in (1, 2, 3))
            assert calls == [(3, "possvm")]                          # no second read
            await _key(pilot, "escape")
            assert app.view == "overview" and app.tab == "results" and app.focused is rt
            assert app._key_at_cursor(rt) == "tfs" and rt.cursor_column == 3
            await _key(pilot, "tab", "o")                            # Jobs tab o: cache reused too
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view == "results" and calls == [(3, "possvm")]
            await _key(pilot, "escape", "tab")
            assert app.tab == "results" and calls == [(3, "possvm")]   # switching never re-reads
    _run(go())


def test_results_tab_p_switches_source_and_R_rereads(cli, monkeypatch):
    write_results(_cfg())
    calls = _count_group_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            await pilot.press("p")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.rt_source == "possvm_prev" and calls[-1] == (3, "possvm_prev")
            assert _rt(app)[0] == ("ALL", 3, 1, 1, 2, 0)
            assert app.query_one("#rtab").border_title == "Results · possvm_prev"
            await pilot.press("enter")                               # window opens on prev, cached
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.res_source == "possvm_prev" and len(calls) == 2
            await _key(pilot, "escape")
            await pilot.press("R")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(calls) == 3 and app.rt_source == "possvm_prev"
    _run(go())


def test_results_tab_sort_hide_and_header_keep_all_pinned(cli, monkeypatch):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            rt = app.query_one("#rtab")
            rt.move_cursor(row=1, column=3)                          # OGs
            await pilot.pause()
            await _key(pilot, "h")
            assert [r[0] for r in _rt(app)] == ["ALL", "tfs"]
            assert rt.border_title == "Results · possvm · only ogs > 0"
            await _key(pilot, "h")
            assert len(_rt(app)) == 4
            rt.move_cursor(row=0, column=0)
            await pilot.pause()
            await _key(pilot, "h")                                   # group: not a count
            assert app.rt_hide is None
            await _key(pilot, "s")                                   # s on a cell: group ▲
            assert rt.sort == ("group", False) and [r[0] for r in _rt(app)] == ["ALL", "cal", "slc", "tfs"]
            await _key(pilot, "up", "right", "right", "right", "enter")   # header: OGs ▼
            assert rt.sort == ("ogs", False) and _heads(app, "#rtab")[3] == "OGs ▼"
            assert [r[0] for r in _rt(app)][:2] == ["ALL", "tfs"]
            app.load_now()                                           # refresh: sort kept, no read
            await pilot.pause()
            assert rt.sort == ("ogs", False) and [r[0] for r in _rt(app)][:2] == ["ALL", "tfs"]
    _run(go())


def test_results_tab_waits_for_first_refresh_and_shows_progress(cli, monkeypatch):
    write_results(_cfg())
    calls = _count_group_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app._ov_inputs = (set(), {}, set(), {})                  # as before the first refresh
            await pilot.press("tab")
            await pilot.pause()
            assert app.tab == "results" and calls == [] and app._og_cache is None
            app.load_now()                                           # first data: the read starts
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(calls) == 1 and app._og_cache is not None
            app.query_one("#rtab").add_class("loading")
            app._rt_progress(app._rt_gen, 100, 1915)
            assert "loading 100/1915…" in app._rt_foot
            app._rt_progress(app._rt_gen - 1, 150, 1915)              # stale generation: ignored
            assert "150/1915" not in app._rt_foot
    _run(go())


def test_results_tab_counts_unreadable_hgs(cli):
    write_results(_cfg())
    (_cfg().outdir / "possvm/tfs.A.HG11.generax.support.tree.ortholog_groups.csv").write_text(
        OG_HEAD + "broken\n")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            assert _rt(app)[0] == ("ALL", 3, 2, 2, 5, 1)
            assert "1 HG unreadable" in app._rt_foot
    _run(go())


def test_results_tab_keys_touch_no_files_or_slurm(cli, monkeypatch):
    write_results(_cfg())

    def boom(*a, **k):
        raise AssertionError("file or SLURM access on a Results tab key")

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _results_tab(app, pilot)
            monkeypatch.setattr(core, "ready_set", boom)
            monkeypatch.setattr(core.report_status, "done_by_stage", boom)
            monkeypatch.setattr(core.report_status, "nonempty_files", boom)
            monkeypatch.setattr(tui.model, "read_ogs", boom)
            monkeypatch.setattr(tui.model, "_slurm", boom)
            app.query_one("#rtab").move_cursor(row=0, column=3)
            await _key(pilot, "s", "h", "h", "up", "right", "enter", "down", "f", "c",
                       "shift+tab", "tab")
            assert app.tab == "results" and app.query_one("#rtab").sort == ("genes", False)
    _run(go())
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests -q -p no:cacheprovider -k "og_group_rows or tab_switches or reads_once or p_switches_source_and_R or sort_hide_and_header or waits_for_first or unreadable_hgs or tab_keys_touch"` — Expected: FAIL (`module 'phylocli.model' has no attribute 'og_group_rows'`; `'PhyloApp' object has no attribute '_tab_text'` / `'rt_shown'`).

- [ ] **Step 3: Implement `model.og_group_rows`** (append to `phylocli/model.py`; `collections` and `dataclass` are imported there):

```python
# ---- Results tab (TUI first screen) ----------------------------------------------------------
@dataclass
class OGGroupRow:
    group: str
    hgs: int                   # expected HGs of the group
    with_output: int           # HGs with a non-empty ortholog_groups.csv (unreadable included)
    ogs: int
    genes: int
    zero: int                  # OGs with orthogroup_support exactly 0
    unreadable: int            # HGs whose file could not be parsed (HGOgs.error)


def og_group_rows(groups, exp, by: str, rows) -> list[OGGroupRow]:
    """One row per group name (ALL = every expected HG; else group_key(hg, by) == name), in
    the order given, summed over `rows` ([HGOgs] of any HGs; others count as without output).
    Pure: no file access."""
    by_hg = {r.hg: r for r in rows}
    members: dict[str, list[str]] = collections.defaultdict(list)
    for hg in exp:
        members[group_key(hg, by)].append(hg)
    out = []
    for g in groups:
        hgs = list(exp) if g == "ALL" else members.get(g, [])
        rs = [by_hg[h] for h in hgs if h in by_hg]
        ok = [r for r in rs if not r.error]
        ogs = [o for r in ok for o in r.ogs]
        out.append(OGGroupRow(g, len(hgs), len(rs), len(ogs), sum(len(o.genes) for o in ogs),
                              sum(1 for o in ogs if o.support == 0), len(rs) - len(ok)))
    return out
```

- [ ] **Step 4: Implement the tab in `tui.py`.**

`PANE_TITLES`: add `"#rtab": "Results"` after `"#overview": "Overview"` (covered by `test_panes_are_named_top_left`; the title stays `Results` until the first read).

Insert immediately before `class SortTable(DataTable):`:

```python
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
```

CSS: add after the `#ovfoot` rule:

```
    #tabbar { height: 1; }
    #rtab { height: 1fr; border: round $primary; }
    #rtab:focus { border: round orange; }
    #rtab.loading { opacity: 40%; }
```

`__init__`: after `self.ov_shown: list = []  …`, add

```python
        self.tab = "jobs"                       # first-screen tab: "jobs" | "results"; tab
        self.rt_source: "str | None" = None     # Results tab source; None = default_source
        self.rt_hide: "str | None" = None       # Results tab: count column name; h
        self.rt_rows: list = []                 # [model.OGGroupRow], Jobs group order
        self.rt_shown: list = []
        self._og_cache: "dict | None" = None    # {source, rows: {hg: HGOgs}, hgs: frozenset}
        self._rt_gen = 0
        self._rt_note = ""
        self._rt_foot = ""
        self._tab_text = ""
```
and after the `self.res_source: …` line add
```python
        self._res_want: "str | None" = None     # source asked for by the opener (Results tab)
```

`compose`: inside `Vertical(id="ov")`, put the tab bar directly above `#overview` and the Results-tab table directly below it (`#ovfoot` stays last):

```python
            yield Static("", id="tabbar")
            yield SortTable(id="overview", cursor_type="cell", header_height=2)   # step1/step2 header
            yield SortTable(id="rtab", cursor_type="cell")
```

`on_mount`: after `self.query_one("#overview", SortTable).set_cols(OV_COLS)` add `self.query_one("#rtab", SortTable).set_cols(RT_COLS)` (before the `on_sort` loop).

`_apply`: right after the `if snap["by"] != self.by: … else: self._fill_overview(snap["ov_rows"])` block, add `self._maybe_load_rtab()`.

Replace `_show_view` with the version below and add the tab and Results-tab methods after it:

```python
    def _show_view(self) -> None:
        self.query_one("#ov").display = self.view == "overview"
        self.query_one("#hgview").display = self.view == "hgs"
        self.query_one("#resv").display = self.view == "results"
        jobs = self.tab == "jobs"
        self.query_one("#overview").display = jobs
        self.query_one("#rtab").display = not jobs
        self._set_tabbar()
        first = "#overview" if jobs else "#rtab"
        self.query_one({"overview": first, "hgs": "#hgs", "results": "#res"}[self.view]).focus()
        if self.view == "overview":
            self._overview_footer() if jobs else self._rt_footer()
        self._update_help()                      # Part G's strip: help follows view and tab

    def _set_tabbar(self) -> None:
        """`[Jobs] │ Results`: the active tab bracketed and reversed."""
        names = (("jobs", "Jobs"), ("results", "Results"))
        self._tab_text = " │ ".join(f"[{n}]" if k == self.tab else n for k, n in names)
        txt = Text()
        for i, (k, n) in enumerate(names):
            txt.append(" │ " if i else "")
            txt.append(f"[{n}]" if k == self.tab else n, style="reverse bold" if k == self.tab else "")
        txt.append("   tab: switch", style="dim")
        self.query_one("#tabbar", Static).update(txt)

    def _switch_tab(self) -> None:
        self.tab = "results" if self.tab == "jobs" else "jobs"
        self._show_view()
        self.refresh_bindings()                  # p shows on the Results tab only
        self._maybe_load_rtab()

    def action_focus_next(self) -> None:
        """tab: on the first screen it switches Jobs / Results; elsewhere it moves focus."""
        if self.view == "overview" and not isinstance(self.screen, ModalScreen):
            self._switch_tab()
            return
        super().action_focus_next()

    def action_focus_previous(self) -> None:
        if self.view == "overview" and not isinstance(self.screen, ModalScreen):
            self._switch_tab()
            return
        super().action_focus_previous()

    # ---- Results tab --------------------------------------------------------------------------
    def _rt_loading(self) -> bool:
        return self.query_one("#rtab").has_class("loading")

    def _maybe_load_rtab(self) -> None:
        """Start the one read of every expected HG when the Results tab is shown and nothing is
        cached or loading; waits for the first refresh (no expected HGs known yet)."""
        if (self.view == "overview" and self.tab == "results" and self._og_cache is None
                and not self._rt_loading() and self._ov_inputs[0]):
            self._reload_rtab()

    def _reload_rtab(self) -> None:
        self._rt_gen += 1
        self._og_cache = None
        self.query_one("#rtab").add_class("loading")
        self._rt_note = "loading…"
        self._rt_footer()
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

    def _apply_rtab(self, snap: dict) -> None:
        if snap["gen"] != self._rt_gen:          # superseded by R or p
            return
        self.query_one("#rtab").remove_class("loading")
        self.rt_source = snap["source"]
        ok = not snap["note"]                    # a failed read caches nothing reusable
        self._og_cache = dict(source=snap["source"], rows={r.hg: r for r in snap["rows"]},
                              hgs=frozenset(snap["hgs"]) if ok else frozenset())
        self._rt_note = snap["note"]
        self._fill_rtab()

    def _fill_rtab(self) -> None:
        """Results tab rows: the Jobs groups, counted over the cached files (memory only)."""
        t = self.query_one("#rtab", SortTable)
        cache = self._og_cache or {}
        self.rt_rows = model.og_group_rows([r.group for r in self.ov_rows], self._ov_inputs[0],
                                           self.by, cache.get("rows", {}).values())
        self.rt_shown = rt_order(self.rt_rows, t.sort, self.rt_hide)
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
            bad = sum(1 for x in self._og_cache["rows"].values() if x.error)
            if bad:
                line += f" · {bad} HG{'' if bad == 1 else 's'} unreadable"
            lines.append(line)
        self._rt_foot = "\n".join(lines)         # status only: the keys are in the strip's help
        self.query_one("#ovfoot", Static).update(escape(self._rt_foot))
```

`_help_for` (Part G's per-view key help in the strip): replace its final `return "\n".join([ "[b]Overview[/]", … ])` (the overview branch) with a Results-tab branch plus the Jobs help with the two new keys:

```python
        if self.tab == "results":                # the first screen's Results tab
            return "\n".join([
                "[b]Overview · Results tab[/]  POSSVM output per group",
                "enter / o: open the group's Results · p: possvm ↔ possvm_prev · tab: Jobs",
                "s: sort by the column · h: hide rows with 0 in the column · c/f: category/family",
                "↑ on the first row: header (←/→ column, enter/s sort) · R: re-read · q: quit",
                "⚠ sup 0 = OGs with support 0 (GeneRax bug case)"])
        return "\n".join([
            "[b]Overview[/]",
            glyphs,
            "search/cluster count families, the other stages HGs",
            "enter: open the group at that stage · o: results · c/f: category/family · tab: Results",
            "s: sort by the column (↑ on the first row: header) · h: only actionable at the column",
            "R: refresh · q: quit · default view: failed+ready"])
```
(`test_strip_with_logo_and_help_is_in_every_view` checks `"o: results"`, `"█ done"` and three distinct helps on the Jobs tab: unchanged. `_switch_tab` → `_show_view` → `_update_help()` refreshes it per tab.)

`_fill_overview`: at its end (after `self._overview_footer()`), add

```python
        if self._og_cache is not None:          # same groups (c / f, refresh) on the Results tab
            self._fill_rtab()
```

`_overview_footer`: first lines become

```python
    def _overview_footer(self) -> None:
        if self.tab != "jobs":                   # #ovfoot belongs to the Results tab then
            return
```

`check_action`: replace `if action in ("toggle_source", "member_filter"): return self.view == "results"` with

```python
        if action == "toggle_source":
            return self.view == "results" or (self.view == "overview" and self.tab == "results")
        if action == "member_filter":
            return self.view == "results"
```

`action_sort`: the first-screen table depends on the tab:

```python
    def action_sort(self) -> None:
        """s with the first-screen table not focused (focused, the table's own s handles it)."""
        if self.view == "overview":
            t = self.query_one("#overview" if self.tab == "jobs" else "#rtab", SortTable)
            t.sort_by(t.cursor_column)           # no-op on the │ separator
```

`_resorted`: add after the `overview` branch

```python
        elif t.id == "rtab":
            self._fill_rtab()
```

`action_hide`: insert at its top

```python
        if self.view == "overview" and self.tab == "results":
            t = self.query_one("#rtab", SortTable)
            name = t.cols[t.cursor_column].name if t.cols else None
            if name in (None, "group"):
                self.notify("h: move to a count column first", severity="warning")
                return
            self.rt_hide = None if self.rt_hide == name else name
            self._fill_rtab()                    # in memory only
            return
```

`on_data_table_cell_selected`: insert at its top

```python
        if self.view == "overview" and event.data_table.id == "rtab":
            self._open_results(event.cell_key.row_key.value, self.by, source=self.rt_source)
            return
```

`on_data_table_cell_highlighted`: add `elif event.data_table.id == "rtab": self._rt_footer()` after the overview branch.

`action_refresh`: insert at its top

```python
        self._og_cache = None                    # R re-reads the ortholog-group files too
        if self.view == "overview" and self.tab == "results":
            self._reload_rtab()
```

`action_open_results`: the overview branch becomes two:

```python
        if self.view == "overview" and self.tab == "results":
            group = self._key_at_cursor(self.query_one("#rtab", DataTable))
            if group is not None:
                self._open_results(group, self.by, source=self.rt_source)
        elif self.view == "overview":
            group = self._key_at_cursor(self.query_one("#overview", DataTable))
            if group is not None:
                self._open_results(group, self.by)
```

`_open_results`: signature `def _open_results(self, group: str, by: str, focus: "str | None" = None, source: "str | None" = None) -> None:`; after `self.res_source, self.res_rows, self.res_missing = None, [], 0` add `self._res_want = source                 # None = default_source(), in the worker`.

`_reload_results`: the worker call becomes

```python
        self._load_results(list(self.res_hgs), self.res_source or self._res_want, self._res_gen,
                           self._og_cache)
```

`_load_results`: signature `def _load_results(self, hgs: list, source: "str | None", gen: int, cache: "dict | None" = None) -> None:`; replace its `snap["rows"], snap["missing"] = model.group_ogs(…)` statement with

```python
            if (cache is not None and cache["source"] == snap["source"]
                    and set(hgs) <= cache["hgs"]):   # the Results tab read them: no 2nd read
                snap["rows"] = [cache["rows"][h] for h in hgs if h in cache["rows"]]
                snap["missing"] = len(hgs) - len(snap["rows"])
            else:
                snap["rows"], snap["missing"] = model.group_ogs(
                    self.cfg, hgs, snap["source"], progress=progress,
                    cancelled=lambda: worker.is_cancelled or gen != self._res_gen)
```
(`res_hgs` is sorted by `model.hg_sort_key`, as `group_ogs` sorts, so both paths give the same row order.)

`action_toggle_source`: insert at its top

```python
        if self.view == "overview" and self.tab == "results":
            if self._og_cache is None:           # the first read is still running
                return
            self.rt_source = "possvm_prev" if self._og_cache["source"] == "possvm" else "possvm"
            self._reload_rtab()
            return
```

`action_back` is unchanged: `esc` from the window sets `view = res_from` (`"overview"`), `_show_view` focuses `#rtab` because `tab` is still `"results"`, and the following `load_bg` → `_fill_overview` → `_fill_rtab` keeps the cursor by key.

- [ ] **Step 5: Run** both suites — Expected: N0 + 8 passed.

- [ ] **Step 6: Commit**

```bash
git add phylocli/model.py phylocli/tui.py phylocli/tests/test_model.py phylocli/tests/test_tui.py
git commit -m "tui: Jobs / Results tabs on the first screen (tab); one cached read of every HG's POSSVM output, reused by the Results window

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: species coverage colours (Part D) and overview numbers left of 6-cell bars (Part E)

**Files:**
- Modify: `phylocli/tui.py` (`import re`; `coverage_style`, `_SPP`, `species_text`, `ov_cell` before `_todo_at`; `OV_BAR`; `_fill_overview`; `_show_og`)
- Test: `phylocli/tests/test_tui.py` (append)

**Interfaces:**
- Consumes: `species_lines(stats, outside, width)` output format `f"{phylum.ljust(w)}  {k}/{m} spp  {n} gene(s)"`; `model.bar_segments(counts, width)`; `PhyloApp.OV_GLYPHS`.
- Produces: `coverage_style(k: int, m: int) -> str` (`red` < 1/3 ≤ `yellow` < 2/3 ≤ `green`); `species_text(text: str) -> rich.text.Text` (spans only, plain text unchanged); `ov_cell(c: tuple, width: int, bar: int, glyphs) -> str` (Rich markup); `PhyloApp.OV_BAR = 6`. `_species_text` stays the plain string (existing tests read it).

- [ ] **Step 1: Write the failing tests** (append):

```python
# ---- species coverage colours (D) and overview numbers (E) ------------------------------------
from rich.text import Text  # noqa: E402


def test_coverage_style_thirds():
    assert [tui.coverage_style(k, 3) for k in range(4)] == ["red", "yellow", "green", "green"]
    assert tui.coverage_style(0, 0) == "red" and tui.coverage_style(1, 4) == "red"
    assert tui.coverage_style(1, 2) == "yellow" and tui.coverage_style(5, 5) == "green"


def test_species_text_colours_counts_only_and_never_parses_markup():
    text = "\n".join(["Ctenophora  1/2 spp  2 genes", "  Mlei 2 · [b]x 1",
                      "Chordata    0/3 spp  0 genes", "absent: unknown, [red]"])
    t = tui.species_text(text)
    assert t.plain == text                                   # numbers and names unchanged
    assert [(t.plain[s.start:s.end], str(s.style)) for s in t.spans] == [
        ("1/2 spp", "yellow"), ("0/3 spp", "red"), ("absent: unknown, [red]", "dim")]


def test_species_pane_is_coloured_by_coverage(cli):
    write_results(_cfg())

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            await _open_results(app, pilot, "tfs")
            assert app._species_text.splitlines()[0] == "Ctenophora  1/2 spp  2 genes"
            t = tui.species_text(app._species_text)
            assert [str(s.style) for s in t.spans] == ["yellow", "green", "dim"]
    _run(go())


def test_ov_cell_numbers_left_of_six_cell_bar():
    g = tui.PhyloApp.OV_GLYPHS
    assert tui.PhyloApp.OV_BAR == 6
    cell = tui.ov_cell((1800, 0, 0, 214), 9, 6, g)
    assert Text.from_markup(cell).plain == "1800/2014 █████░"
    assert Text.from_markup(tui.ov_cell((1, 0, 1, 0), 9, 6, g)).plain == "      1/2 ███▓▓▓"
    assert Text.from_markup(tui.ov_cell((0, 0, 0, 0), 3, 6, g)).plain == "0/0 "


def test_overview_cells_show_done_over_total(cli):
    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            c = app.ov_rows[0].per_stage["align"]
            cell = _cells(app, "#overview", 0)[tui.ov_column("align")]
            assert Text.from_markup(cell).plain.startswith(f"{c[0]}/{sum(c)} ")
            assert len(Text.from_markup(cell).plain.split(" ")[-1]) == 6
            col = [Text.from_markup(_cells(app, "#overview", i)[tui.ov_column("align")]).plain
                   for i in range(len(app.ov_shown))]
            assert len({len(x.rsplit(" ", 1)[0]) for x in col if x != "n/a"}) == 1   # right-aligned
    _run(go())
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider -k "coverage or species_text or species_pane_is or ov_cell or done_over_total"` — Expected: FAIL (`module 'phylocli.tui' has no attribute 'coverage_style'` / `'ov_cell'`; `OV_BAR == 10`).

- [ ] **Step 3: Implement.**

Add `import re` after `import os`. Insert immediately before `def _todo_at(`:

```python
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
```

`OV_BAR = 10` → `OV_BAR = 6`.

In `_fill_overview`, right after `t.clear()` (before `for r in self.ov_shown:`), add

```python
        width = {st: max((len(f"{c[0]}/{sum(c)}") for r in self.ov_shown
                          for c in [r.per_stage.get(st)] if c), default=0)
                 for st in OV_COLUMNS if st is not None}     # numbers right-aligned per column
```
and replace the bar lines

```python
                n = model.bar_segments(c, self.OV_BAR)
                cells.append("".join(f"[{fg}]{ch * k}[/]"
                                     for (ch, fg), k in zip(self.OV_GLYPHS, n) if k))
```
with
```python
                cells.append(ov_cell(c, width[st], self.OV_BAR, self.OV_GLYPHS))
```
(Units: `per_stage` already counts families at search/cluster and HGs elsewhere. Sorting/hiding read `per_stage`, not the cell text, so they are unchanged. The footer's per-stage counts stay.)

In `_show_og`, replace `self.query_one("#species", Static).update(text)` with

```python
        self.query_one("#species", Static).update(species_text(text))   # coverage colours
```

- [ ] **Step 4: Run** both suites — Expected: N0 + 5 passed.

- [ ] **Step 5: Commit**

```bash
git add phylocli/tui.py phylocli/tests/test_tui.py
git commit -m "tui: species k/m spp coloured red -> green by coverage; overview cells done/total left of 6-cell bars

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: spinner while history and Results data load (Part F)

**Files:**
Part G's strip already has the status line (`#status`, filled by `_update_status()` with "loading history…" from `_hist_loading` and the Results window's `loading k/n…`). Part F makes that line a spinner and adds the Results tab's read to it.

- Modify: `phylocli/tui.py` (`SPIN_FRAMES`, `class Spinner` before `class PhyloApp`; `compose` (`#status`); `_update_status`; `_reload_rtab`; `_rt_progress`; `_apply_rtab`)
- Test: `phylocli/tests/test_tui.py` (append)

**Interfaces:**
- Consumes: Part G's `_update_status()` (called from `_apply`, `_update_help` ← `_show_view`, `_results_footer` ← `_show_og` / `_res_progress`), `_hist_loading`, `_res_note`, `self._status`; Task 4's `_rt_loading()`, `_rt_note`, `tab`.
- Produces: `SPIN_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"`; `class Spinner(Static)` with `text: str`, `frame: int`, `running: bool` (property), `start(text)`, `stop()`; `#status` is a `Spinner`. `_status` stays the plain text (no glyph), so Part G's tests keep passing; the widget renders `"<frame> <text>"` while running and `""` when stopped. The spinner shows only what the **current** view waits for (HG view: history; Results window: its read; Results tab: its read) — switching away stops it, switching back restarts it while the read is still running.

- [ ] **Step 1: Write the failing tests.** Append:

```python
# ---- spinner (F) ------------------------------------------------------------------------------
def _gated_read_ogs(monkeypatch):
    import threading
    gate = threading.Event()
    real = tui.model.read_ogs

    def gated(*a, **k):
        gate.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(tui.model, "read_ogs", gated)
    return gate


def test_spinner_turns_while_results_window_loads_and_stops_on_apply(cli, monkeypatch):
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            spin = app.query_one("#status")
            assert not spin.running and str(spin.render()) == ""        # idle: empty
            app.query_one("#overview").move_cursor(row=_ov_row(app, "tfs"))
            await _key(pilot, "o")
            assert spin.running and spin.text == "loading…" == app._status
            f0 = spin.frame
            await pilot.pause(0.4)                                     # ~8 frames/s
            assert spin.frame != f0
            assert str(spin.render()) == f"{tui.SPIN_FRAMES[spin.frame]} loading…"
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not spin.running and str(spin.render()) == "" and app._status == ""
    _run(go())


def test_spinner_stops_on_esc_during_results_load(cli, monkeypatch):
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _key(pilot, "o")                                     # ALL
            spin = app.query_one("#status")
            assert spin.running
            await _key(pilot, "escape")                                # cancel
            assert app.view == "overview" and not spin.running
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not spin.running
    _run(go())


def test_spinner_on_results_tab_and_for_history(cli, monkeypatch):
    import threading
    write_results(_cfg())
    gate = _gated_read_ogs(monkeypatch)

    async def go():
        app = tui.PhyloApp(_cfg(), refresh_s=3600)
        async with app.run_test() as pilot:
            app.load_now()
            await pilot.pause()
            await _key(pilot, "tab")
            spin = app.query_one("#status")
            assert spin.running and spin.text == "loading…"
            await _key(pilot, "tab")                                   # Jobs tab: not its wait
            assert not spin.running
            await _key(pilot, "tab")
            assert spin.running
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not spin.running and app._og_cache is not None
            from phylocli import history
            real = history.attempts
            hold = threading.Event()
            monkeypatch.setattr(history, "attempts", lambda *a, **k: hold.wait(10) and real(*a, **k))
            app.by_stage = {}                                          # no HG-view history yet
            app.open_group("tfs")
            await pilot.pause()
            assert spin.running and spin.text == "loading history…"
            hold.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.by_stage and not spin.running
    _run(go())
```

- [ ] **Step 2: Run** `python3 -m pytest phylocli/tests/test_tui.py -q -p no:cacheprovider -k "spinner"` — Expected: FAIL (`AttributeError: 'Static' object has no attribute 'running'`).

- [ ] **Step 3: Implement.**

Insert immediately before `class PhyloApp(App):`:

```python
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
        self.update(f"{SPIN_FRAMES[self.frame]} {self.text}")
```

`compose`: in the strip's `Vertical(id="helpbox")`, replace `yield Static("", id="status")` with

```python
                yield Spinner(id="status")          # Part F: spinner + status text
```
(the existing `#status { height: 1; color: $warning; }` CSS applies unchanged).

`_update_status`: add a Results-tab branch and drive the spinner instead of a plain `update`:

```python
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
        if text:
            spin.start(text)                     # turns until the data are applied ...
        else:
            spin.stop()                          # ... or the view no longer waits (esc, tab)
```

Call `self._update_status()` in the three Results-tab places (the window's load already reaches it through `_results_footer`, the history through `_apply` / `_show_view`):
- in `_reload_rtab`, after `self._rt_footer()`;
- in `_rt_progress`, after `self._rt_footer()`;
- in `_apply_rtab`, after `self._fill_rtab()`.

Stops: on apply (`_apply_results` → `_show_og` → `_results_footer`; `_apply_rtab`; `_apply` with history), on `esc` (`action_back` → `_show_view` → `_update_help`), on cancel (a superseded generation never leaves the shown view's `.loading`/note at `loading…` once the newer load lands), and on leaving the view or tab.

- [ ] **Step 4: Run** both suites — Expected: N0 + 3 passed (Part G's `test_open_group_before_hg_data_shows_loading` and `test_strip_with_logo_and_help_is_in_every_view` unchanged and passing).

- [ ] **Step 5: Commit**

```bash
git add phylocli/tui.py phylocli/tests/test_tui.py
git commit -m "tui: the strip's status line turns a braille spinner while history, the Results window or the Results tab load

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (09/10/2026)

- **Spec coverage.** A: tabs, `[Jobs] │ Results`, `tab`/`shift+tab`, same rows/`by`, columns (no focal species), `p`, `s`/`h` with ALL pinned, `enter`/`o` → window, `esc` back with cursor, one read with progress/cancel, cache until `R`/`p`, window reuse, Jobs tab unchanged — Task 4. B: header mode on Jobs, Results tab, `2 HGs`, `Results`/`OGs`/`members` (not `1 Stages`/`3 Arrays`), `▲`/`▼` always shown, one sorted column, kept across refresh/regroup, numbers desc / text asc, `│` skipped, stage columns on failed+ready (via the unchanged `ov_order`), `s` = header sort — Tasks 1, 2, 4. D — Task 5. E — Task 5. F — Task 6 (in Part G's `#status` line; stops on apply, `esc`, cancel, leaving the view/tab). Error handling: unreadable count — Task 4; header mode vs typing — Task 2. Part C fixes — Task 3. G — landed separately (`b313b1d`, `6f04984`), not in this plan; Task 4 adds the Results-tab key help to its `_help_for`.
- **Placeholders:** none; every code step carries its code.
- **Type consistency:** `SortCol(name, label, numeric)`, `SortTable.sort/cols/header/hcol/on_sort`, `sort_rows(rows, sort, keys)`, `_fill_ogs(keep=None)`, `_open_results(group, by, focus=None, source=None)`, `_load_results(hgs, source, gen, cache=None)`, `_og_cache = {"source", "rows", "hgs"}`, `OGGroupRow` field names = `RT_COLS` names — used identically across tasks.
- **Review Focus:** each line has its test in the owning task (listed above).
