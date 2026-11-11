# druid Counts Heatmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A species × gene-group count heatmap (class → family → HG → OG, plus Custom) reachable with `H` from druid's Results tab and Results window.

**Architecture:** Pure data in `druid/counts.py` (columns, species axis, z-scores, colours); a Textual `CountsScreen` in `druid/counts_tui.py` that renders it next to the vendored treeview's compact species cladogram; `druid/tui.py` only gains the `H` opener, a tree-opening callback, and key-table rows.

**Tech Stack:** Python 3, Textual (`DataTable`, `Screen`), vendored `treeview` (`druid/vendor/treeview`: `model.TreeModel`, `layout.clado_rows`, `layout.clado_order`, `keys.KeysScreen`, `keys.missing_keys`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-11-druid-counts-heatmap-design.md` (read it: tables of levels, keys, errors are authoritative and not repeated here).

## Global Constraints

- Repo: `/home/grygoriyzolotarov/Documents/projects/phylogenies/druid`. Commit on `main` (Grygoriy's repo convention; no worktree).
- Before EVERY commit run the full suite: `python3 -m pytest -q -p no:cacheprovider -rf 2>&1 | grep -E "passed|failed"` and confirm `0 failed` from that line (a `| tail` exits 0 on failures). Baseline: 782 passed, 1 skipped.
- Edit code with Edit/Write (fail loudly), never `sed`.
- Write nothing outside the project's own directories; the screen reads files only.
- Species code of a gene: `model.species_of(gene)` (id up to the first `_`).
- Family counts = `<outdir>/search/<fam>.genes.list` lines (blank and `#` skipped); HG counts = `model.read_cluster_members(cfg, hg)`; OG counts = `model.HGOgs` / `model.read_ogs`.
- Species tree = `cfg.params["SPECIES_TREE"]`, loaded with `treeview.model.load` into `treeview.model.TreeModel(tree, sep="_")`; rows = shown leaves in `layout.clado_order(m)` order, cladogram = `layout.clado_rows(m, gap=-1)`.
- z-score: per column over the coloured rows, sample SD; SD 0 or a single row → SD 1. Colours: `RdBu` over [zmax, 0, −zmax] (high = red) / `Blues` 0..vmax; fg `#222222` on light, `#eeeeee` on dark, luminance threshold 0.45.
- Cell text: count right-aligned, `·` for 0, `99+` over 99. Column header = 1-based number, width max(3, digits of n columns).
- Quit is `:q!` as elsewhere in druid; the screen does not bind `q`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A family / HG with genes from species not in the species tree → `(not on tree)` row, excluded from z-scores, included in `Σ`. (Task 2 test.)
2. Species tree unreadable or `SPECIES_TREE` unset → `H` shows `species tree unreadable: <error>` and does not push the screen, no crash. (Task 4 test.)
3. A level with zero columns (family with no FASTA yet) → one `no data` line, keys still work, esc goes back. (Task 3 test.)
4. An HG whose OG csv raises `ModelError` → OG level `no data`, error in the status. (Task 3 test.)
5. A collapsed clade then a drill → collapse state kept across levels; `s` sort reset on drill. (Task 3 test.)

---

### Task 1: Column data (`druid/counts.py`)

**Files:**
- Create: `druid/counts.py`
- Test: `tests/test_counts.py`

**Interfaces:**
- Consumes: `druid.core.Config` (`.outdir`), `model.read_cluster_members(cfg, hg) -> list[Member]`, `model.species_of`, `model.HGOgs` (`.hg`, `.ogs`, `.error`), `model.OG` (`.id`, `.name`, `.genes`).
- Produces:
  - `@dataclass Col(id: str, label: str, counts: dict[str, int])` with property `total -> int`.
  - `family_cols(cfg, fams: Iterable[str]) -> tuple[list[Col], int]`
  - `hg_cols(cfg, hgs: Iterable[str]) -> tuple[list[Col], int]`
  - `class_cols(fam_cols: list[Col]) -> list[Col]` (id and label = class)
  - `og_cols(hgogs: model.HGOgs) -> list[Col]` (label `"<HG part>.<n>:<name>"`, e.g. `"HG1.0:T/Tbx19"`)
  - `order_cols(cols, by: set[str] | None = None) -> list[Col]`
  - `zscores(matrix: list[list[int]]) -> list[list[float]]` (rows × cols in, same shape out)
  - `cell_colour(v: int, z: float, mode: str, zmax: float, vmax: int) -> tuple[str, str]` (`mode` in `"z"`, `"abs"`)
  - `fmt_count(v: int) -> str`

- [ ] **Step 1: Write failing tests** in `tests/test_counts.py` on `tmp_path` fixtures with a minimal stand-in cfg (`types.SimpleNamespace(outdir=tmp_path)`):
  - `test_family_cols_counts_species_and_skips`: `search/tfs.A.genes.list` = `"Mlei_g1\nMlei_g2\n\n# c\nHsap_x\n"`, `search/tfs.B.genes.list` empty, `tfs.C` absent → `cols == [Col("tfs.A","tfs.A",{"Mlei":2,"Hsap":1})]`, unreadable == 1 (absent counts; empty is dropped silently).
  - `test_hg_cols_reads_fasta_headers`: `clusters/tfs.A.HG1.fasta` with 3 headers (2 Mlei, 1 Bova) → counts `{"Mlei":2,"Bova":1}`; an HG not in `hgs` but on disk is not returned.
  - `test_class_cols_sums_families`: tfs.A + tfs.B + slc.X → two cols `tfs`, `slc` with summed counts.
  - `test_og_cols_labels_and_totals`: build `model.HGOgs("tfs.A.HG1", [OG...×3])` by hand (use `model.read_ogs` on an `og_csv` from `tests.test_model` written to a tmp `possvm/` dir, or construct `model.OG`s directly) → labels `["HG1.0:T/Tbx19", ...]`, totals match member counts; `HGOgs` with `error` set → `[]`.
  - `test_order_cols_default_and_by_species`: totals desc then id; `by={"Hsap"}` ranks by Hsap count, ties keep default order.
  - `test_zscores`: `[[1],[3]]` → `[[-0.7071…],[0.7071…]]` (sample SD = 1.414); constant column → all 0.0; single row → `[[0.0]]`.
  - `test_cell_colour_ends_and_luminance`: z = zmax → reddest RdBu end with fg `#eeeeee`; z = 0 → near-white with fg `#222222`; abs mode v = vmax → darkest Blues, fg `#eeeeee`; v = 0 → lightest Blues.
  - `test_fmt_count`: `0 → "·"`, `7 → "7"`, `100 → "99+"`.
- [ ] **Step 2:** `python3 -m pytest -q -p no:cacheprovider tests/test_counts.py` → FAIL (module missing).
- [ ] **Step 3: Implement** `druid/counts.py`. No Textual import. RdBu / Blues: interpolate between the ColorBrewer 9-class stops (hard-code the hex stops in the module); luminance = relative luminance of the bg, `> 0.45` → dark fg.
- [ ] **Step 4:** tests pass; full suite `0 failed`.
- [ ] **Step 5: Commit** `git add druid/counts.py tests/test_counts.py && git commit -m "counts: column data, z-scores, colours for the Counts heatmap"`.

### Task 2: Species axis (`druid/counts.py`)

**Files:**
- Modify: `druid/counts.py`
- Test: `tests/test_counts.py`

**Interfaces:**
- Consumes: Task 1 `Col`; `treeview.model.TreeModel`, `treeview.layout.clado_order`, `clado_rows` (import `treeview` as `druid/tui.py` does — `core` puts `druid/vendor` on `sys.path`).
- Produces:
  - `load_species_model(cfg) -> TreeModel` (raises `OSError`/`ValueError` with a message when `SPECIES_TREE` is unset, missing or unparsable).
  - `@dataclass Axis(leaves: list[int], labels: list[str], tips: list[frozenset[str]], clado: list)` — one entry per shown leaf in drawing order; `labels` = tip name or `"<first tip>… (k spp.)"` for a collapsed clade; `clado` = the `clado_rows(m, gap=-1)` Text per row.
  - `axis(m: TreeModel) -> Axis`
  - `@dataclass Grid(rows: list[list[int]], off_tree: list[int], off_codes: dict[str, int], sums: list[int], row_totals: list[int])`
  - `grid(cols: list[Col], ax: Axis) -> Grid` (row i = sum over `ax.tips[i]`; `off_tree` per column = counts of species in no tip; `sums` per column = all genes).
  - `collapse_up(m: TreeModel, leaf: int) -> str | None` — the `z` rule: a tip → collapse its parent; a collapsed clade → expand it and collapse its parent; the root is never collapsed (return `"whole tree"` then, else None).

- [ ] **Step 1: Failing tests** with `SP4 = "((Mlei:1,Bova:1)Cteno:1,(Hsap:1,Nvec:1)Para:1);"` (import from `tests.test_model`):
  - `test_axis_rows_in_tree_order`: labels `["Mlei","Bova","Hsap","Nvec"]` (assert against `clado_order` leaves, not a hard-coded guess if drawing order differs), `len(clado) == 4`.
  - `test_collapse_sums_clade`: `collapse_up` on Mlei's leaf → 3 rows; the clade row's count == Mlei + Bova; `collapse_up` again on that row → collapsing the root refused, returns `"whole tree"`, rows unchanged.
  - `test_grid_off_tree_and_sums`: a col with `{"Mlei":2,"Zzz":3}` → `off_tree == [3]`, `off_codes == {"Zzz":3}`, `sums == [5]`, Mlei row 2.
  - `test_load_species_model_errors`: unset param, missing file, `"((("` → raises with a message.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** pass; full suite `0 failed`.
- [ ] **Step 5: Commit** `"counts: species axis, collapse, grid"`.

### Task 3: `CountsScreen` (`druid/counts_tui.py`)

**Files:**
- Create: `druid/counts_tui.py`
- Test: `tests/test_counts_tui.py` (Textual pilot; `pytest.importorskip("textual")`)

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `class CountsScreen(Screen)` with `__init__(self, cfg, m: TreeModel, fam_cols: list[Col], hg_cols: list[Col], level: str, scope: str | None, *, unreadable: int = 0, og_source: Callable[[str, str], model.HGOgs] = ..., open_tree: Callable[[str, str, "model.OG | None", set[str]], None] | None = None, og_search: Callable[[str], list[tuple[str, model.OG]]] | None = None, reload: Callable[[], tuple[list[Col], list[Col], int]] | None = None, focus_col: str | None = None)`.
    - `level` ∈ `"class" | "family" | "hg" | "og" | "custom"`; `scope` = the class id (family level), family id (hg level), HG id (og level), None at class.
    - `og_source(hg, source) -> HGOgs` (source `"possvm"`/`"possvm_prev"`); the app passes a function backed by its OG cache, falling back to `model.read_ogs`.
    - `open_tree(hg, source, og_or_None, species_to_mark)`; `og_search(query) -> [(hg, OG)]`; `reload()` re-reads family/HG cols.
  - Attributes tests read: `level`, `scope`, `mode` (`"z"`/`"abs"`), `cols` (shown `list[Col]`), `sort_row` (int | None), `source`, `custom: list[tuple[str, OG]]`, `status` (last status text).
- Layout: a `DataTable` `#counts` (cell cursor) with fixed columns cladogram and species label, numbered columns, `total`; `Static #legend` one line; `Static #cstatus`. Border title = breadcrumb `Counts · tfs › tfs.T-box › HG1`.
- Keys: exactly the spec's key table except `t`/`/`/`p` depend on the callbacks (`None` → status `not available here`). `?` pushes `KeysScreen` with a `COUNTS_KEYS` table; test `missing_keys(CountsScreen.BINDINGS, COUNTS_KEYS)` is empty. Loading of family/HG cols is NOT in this screen (the app passes them); `R` calls `reload` in a worker and redraws.

- [ ] **Step 1: Failing pilot tests** (host app: `class _Host(App)` pushing the screen in `on_mount`; data from Task 1/2 fixtures, SP4 tree):
  - `test_counts_drill_and_back`: open at class → enter → family level of that class → enter → hg → enter → og; esc ×3 back to class; esc at origin pops the screen.
  - `test_counts_opened_at_family_closes_at_family`: opened at `"family"` with scope `tfs`: esc pops immediately.
  - `test_counts_c_s_z_e`: `c` flips `mode` and status `colour: absolute`; `s` sets `sort_row`, cols reordered by that row; `s` again restores default; `z` reduces rows by 1; `e` restores; drilling keeps collapse, resets `sort_row` to None.
  - `test_counts_no_data_level`: a family with no HG cols → table shows one row `no data`; esc still goes back.
  - `test_counts_og_error`: `og_source` returns `HGOgs(hg, [], error="bad csv")` → `no data` and status contains `bad csv`.
  - `test_counts_t_calls_open_tree`: at hg level, cursor on a Mlei cell, `t` → callback got `(hg, "possvm", None, {"Mlei"})`; at class level `t` → status `t: HG or OG level only`.
  - `test_counts_p_and_custom`: `p` at og flips `source` to `possvm_prev` and calls `og_source` with it; at class status `p: OG level only`; `/` + `T/Tbx` + enter with an `og_search` stub returning 2 OGs → level `custom`, 2 cols; `x` → 1 col.
  - `test_counts_keys_table_complete`: `missing_keys(...) == []`.
  - `test_counts_off_tree_row_and_sigma`: an off-tree species → a `(not on tree)` row and a `Σ` row whose cells equal column totals.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: Implement** `druid/counts_tui.py`. Cells as `rich.text.Text(fmt_count(v), style=f"{fg} on {bg}", justify="right")`; `(not on tree)` and `Σ` rows uncoloured. Status on cursor move: `<label> · <species or clade (k spp.)> · <count> genes · z <z:.1f>`. Legend: from the cursor column onward, `n label` entries that fit one line, cursor's entry bold.
- [ ] **Step 4:** pass; full suite `0 failed`.
- [ ] **Step 5: Commit** `"counts: CountsScreen (drill, colour, sort, collapse, custom)"`.

### Task 4: Wire `H` into the app, tree opening, docs

**Files:**
- Modify: `druid/tui.py` (app `BINDINGS` near line 602; `KEYS["overview_results"]` and `KEYS["results"]`; a new `action_counts`; a tree-opening helper reusing `_load_tree`'s TreeModel build)
- Modify: `docs/reference.md` (Results section: `H` and the screen's keys), `TODOs.md` (Sub-project 4 → done)
- Test: `tests/test_tui.py`

**Interfaces:**
- Consumes: Task 3 `CountsScreen`, Task 2 `load_species_model`, Task 1 `family_cols`, `hg_cols`; app state `self.tab`, `self.view`, `#rtab`, `self.by`, `self._key_at_cursor`, `self._cur_res()`, `self._cur_og()`, `self._og_cache` (`{source, rows: {hg: HGOgs}, hgs}`), `self._ov_inputs[0]` (expected HGs), `core.family_ids(cfg)`.
- Produces: `PhyloApp.action_counts()` bound to `H` ("counts"); opener table exactly as the spec's "Opening (`H`)" table (Results tab: ALL → class; category row → family of that class; family row (`self.by == "family"`) → hg of that family; Results window `#res` → og of that HG; `#ogs`/`#members` → og of its HG with `focus_col` = that OG id). Family/HG cols are read in a worker (own group) with the status `reading counts k/n`, cached on the app for the session; `R` in the screen re-reads.
- `open_tree` callback: builds the TreeModel as `_load_tree` does (refactor the shared part into `_tree_model(hg, source) -> (TreeModel, notes)` used by both), highlights the OG members or every tip whose species is in the given set, pushes the same `DruidTreeScreen`; failures are a `notify` warning.
- `og_search(query)`: case-insensitive substring over OG id/name, gene ids and HG id across `self._og_cache["rows"]`; no cache → status `OGs still loading` and the Results-tab read is started (reuse the existing loader).

- [ ] **Step 1: Failing tests** (use `write_results(_cfg())` and add `search/*.genes.list` + `clusters/*.fasta` in the fixture dir for tfs.A):
  - `test_H_on_results_tab_all_opens_class_level`, `..._category_row_opens_family_level`, `test_H_in_results_window_opens_og_level` (cursor on `#ogs` row 1 → `focus_col == "tfs.A.HG1.1"`).
  - `test_H_with_bad_species_tree_warns`: overwrite `SPECIES_TREE` with `"((("` → no `CountsScreen` pushed, a notification containing `species tree unreadable`.
  - `test_counts_t_opens_tree_screen`: in the screen at hg level press `t` → a `TreeScreen`-derived screen on top.
  - `test_H_listed_in_key_tables`: `"H"` appears in `KEYS["overview_results"]` and `KEYS["results"]`, and the existing `missing_keys` checks still pass.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: Implement**; update `docs/reference.md` and `TODOs.md`.
- [ ] **Step 4:** pass; full suite `0 failed`.
- [ ] **Step 5: Commit** `"tui: H opens the Counts heatmap from Results"`.
