# phylocli × treeview — open an HG's gene tree from Results (design, 12/10/2026)

## Intent (Grygoriy)

From phylocli's Results window, look at the gene tree behind the orthogroups: press a key, see the
tree in the terminal with the orthogroups on it, go back. Asked for on 12/10/2026, with these
decisions:

- treeview is **vendored** into phylocli (not imported from `~/projects/treeview`).
- The tree opens **where the cursor is** (HG → whole tree; OG → its MRCA, members highlighted;
  member → its tip).
- Colour modes are **toggled** with one key (species → each metadata column → species).
- Both apps get a **`?` key screen**; the help text block at the top shrinks to one line.

## Scope

Two repos:

| repo | where | what changes |
|---|---|---|
| treeview | cluster `~/projects/treeview` (mount `~/ant/gzolotarov/projects/treeview`), branch `main` | T1–T5 below |
| phylocli | `~/Documents/projects/phylogenies/phylocli-wt`, branch `phylocli`, deployed to v3 | P1–P3 below |

treeview changes land in treeview first and reach phylocli only through the vendoring script (P1).

⚠ Blocker at the time of writing: `/users/asebe` is out of quota ("No space left on device" on
every write), so treeview cannot be committed until space is freed. Work order: phylocli-side
pieces that need no treeview change can proceed first.

## treeview

### T1. `--meta` reads POSSVM's tab-separated `.csv`

POSSVM's `*.ortholog_groups.csv` is tab-separated. `load_meta` currently parses any `.csv` as
comma-separated, so the real file loads with **0 columns** (measured on
`results/possvm/tfs.T-box.HG1.generax.support.tree.ortholog_groups.csv`: 488 rows, `cols []`).
Rule: a `.csv` whose first non-empty line contains a tab is read as TSV; otherwise as CSV (quoted
commas kept). Other suffixes: TSV, as now.

### T2. `c` cycles colour modes

`c` no longer prompts for a column. Each press advances: species colour → metadata column 1 → … →
column N → species colour. The status line names the mode (`colour: species` /
`colour: orthogroup · 17 values`). With no metadata, `c` says "no metadata columns" and stays on
species. Uses the existing `TreeModel.set_colour_by(col)` (`""`/None = species).

### T3. `?` key screen

- A `KeysScreen` (modal) lists every key, grouped: Move · Views · Collapse · Search · Colour &
  metadata · Edit & export · Quit. `esc`, `?` or `q` closes it.
- The key list is one data structure (group → [(key, description)]) and both the screen and the
  one-line hint are built from it, so they cannot drift.
- The 4-line `HELP` text at the top of `TreeScreen` becomes one line: `? keys · q quit`.

### T4. Tip names never off-screen

Measured 12/10/2026 (T-box HG1, 488 tips, headless): at 80 columns the cladogram rows are 89
columns wide in a 76-column view, so names start past the right edge; at 200 columns they fit
(181/196). Cause: the branch area is `width - 40`, but each level has a minimum width, so a deep
tree overruns it.
Rule: in the cladogram, when the widest row (branches + label) exceeds the view width, the
horizontal step per level shrinks (down to 1 column per level) until the names fit; only when even
1 column per level overruns does the view scroll horizontally. Applies to both the scaled and the
unscaled cladogram and to compact mode.

### T5. Embedding hook

- `TreeScreen(model, view="clado", title="", path=None, focus=None, highlight=None)`:
  - `focus`: a node id; the cursor starts there (revealed if inside a collapsed clade).
  - `highlight`: a collection of node ids; those tips are drawn with a marker (bold + reverse of
    their colour) and become the `n`/`N` hit list, as if they were search results. `esc` clears
    the highlight like it clears a search.
- `TreeModel.mrca(ids) -> int`: the deepest node whose subtree contains every id
  (root when ids is empty).
- `TreeModel.tip(name) -> int | None`: node id of a tip by name.
- `TreeScreen` must work pushed on top of another app's screen stack: `esc` with nothing to clear
  pops it (`app.pop_screen()`), returning to the caller. Standalone, `TreeApp` keeps its current
  behaviour (esc on the default screen does not blank the app).

## phylocli

### P1. Vendored copy

- Path: `phylocli/vendor/treeview/` (the package directory, without `tests/`).
  `phylocli/vendor` is added to `sys.path` where `workflow/` is (core), so the vendored code keeps
  its own absolute `from treeview import …` imports unchanged.
- `phylocli/vendor/treeview/VENDORED`: source repo path, source commit (full hash), date.
- `phylocli/vendor/update_treeview.sh`: copies `~/ant/gzolotarov/projects/treeview/treeview/` (or
  `$TREEVIEW_SRC`) into place, excluding `tests/` and `__pycache__/`, and writes `VENDORED` with
  the source's `HEAD` (read via `ssh login1.hpc.crg.es git -C ~/projects/treeview rev-parse HEAD`,
  because git on the mount fails). Refuses when the source has uncommitted changes.
- The vendored copy is never edited in place; changes go to treeview, then the script runs.
- Dependency: ete3 (already in the cluster `phylo` env, 3.1.3).

### P2. `t` opens the tree

Available in the Results view (`#res` HGs, `#ogs`, `#members`) and in the overview's Results tab.

Which tree, by the current `p` source:

| source | tree | metadata |
|---|---|---|
| `possvm` | `results/possvm/<HG>.generax.support.tree` | same path + `.ortholog_groups.csv` |
| `possvm_prev` | `results/possvm_prev/<HG>.treefile` | same path + `.ortholog_groups.csv` |

Colours: `model.species_info_path(cfg)` (already in phylocli), species separator `_`.

Where it opens:

| cursor on | focus | highlight |
|---|---|---|
| an HG row (`#res`, overview Results tab) | root | none |
| an OG row (`#ogs`) | `mrca(members of the OG)` | the OG's member tips |
| a member row (`#members`) | that tip | none |

Members are the OG's genes as phylocli already lists them in `#members`. A member id not found
among the tree's tips is skipped; the status line says `k of n members not in the tree` when k > 0.

Loading: the tree and metadata are read in a worker thread (`@work(thread=True)`), the screen is
pushed from `call_from_thread`. Errors never crash the TUI; each is a `notify(..., warning)`:
no tree file for this HG/source, unreadable newick, unreadable metadata (the tree still opens
without metadata).

Title: `<HG> · <source> · <OG or member or "">`.

`esc` in the tree returns to the exact Results state (pane, cursor, filters).

### P3. `?` key screen in phylocli

- Same pattern as T3: one key table per view (overview Jobs tab, overview Results tab, HG view,
  Results), a modal `KeysScreen` listing it, `esc`/`?`/`q` closes.
- The multi-line `#help` block shrinks to one line: the view name and `? keys` (the overview
  glyph legend stays, it is not a key list).
- `t` appears in the Results views' tables.

## Testing

- treeview (pytest, run on the mount from the workstation; py39 venv has textual + ete3):
  T1 TSV-in-.csv + true CSV; T2 cycle order and wrap, no-metadata case; T3 every binding of
  `TreeScreen`/`TreeView` appears in the key table (so a new key cannot be missing from `?`);
  T4 at 80 columns every T-box HG1 cladogram row fits the view and tip names are on screen;
  T5 `mrca`, `tip`, focus inside a collapsed clade, highlight = hits, esc pops when pushed.
- phylocli (pytest, fixtures in `phylocli/tests/data/`): P1 vendored import works with `vendor/`
  on the path; P2 the three focus cases, missing tree → notice, members not in tree counted,
  `p` source picks the other file; P3 every binding appears in that view's key table.
- Real-data check after deploy: T-box HG1 in both sources (488 tips; 17 OGs in `possvm`).

## Out of scope

- Editing trees from phylocli (rename/export work inside treeview as they do standalone, writing
  next to the tree only on `w`, which asks for a path).
- Vendoring any other tool; a GitHub remote for treeview.

## Amendments (plan, 12/10/2026)

Recorded while writing `docs/superpowers/plans/2026-10-12-phylocli-treeview.md`:
- The overview's Results tab rows are groups, not HGs: `t` there only says `open a group's Results (o), then t`.
- Highlighted tips are **bold underline** (reverse is the cursor).
- The tree file is the `.ortholog_groups.csv` name minus that suffix (same files as the P2 table).
- `KeysScreen` lives in treeview (`treeview/keys.py`); phylocli imports it from the vendored copy.
- While a tree or key list is on screen, phylocli's own keys (except `q`) do nothing.
