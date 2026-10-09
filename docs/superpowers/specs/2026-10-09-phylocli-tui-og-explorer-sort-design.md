# phylocli TUI: ortholog-group explorer + overview sort/filter — design

Date: 09/10/2026 · Branch: `phylocli` · Status: designs approved in chat (Grygoriy), spec awaiting review
Builds on: `2026-10-08-phylocli-tui-design.md` (overview, HG view, panes `Overview`, `1 Stages`,
`2 HGs`, `3 Arrays`, `4 Detail`).

## Part A — ortholog-group (OG) explorer

### Goal
From an HG, open its POSSVM orthology result, step through its ortholog groups, and for each OG
see the call and its support and which species carry members — drawn on the species tree.
Grygoriy chose: **call + support** and **species coverage** (not side-by-side possvm vs
possvm_prev, not Mlei-member annotation lines, for now).

### Entry and exit
`o` on the highlighted HG in pane `2 HGs` opens a full-screen `OGScreen` for that HG; `esc` back
(HG cursor kept). Works from any HG-view filter and stage.

### Layout
```
tfs.T-box.HG1 · possvm (post-GeneRax) · [p] possvm_prev                       esc back
OG                      genes spp  support  ref.ortholog  ref.sup │ species tree (binary, 59)
▸ HG1.0  T/Tbx19          69   41    78.4   T/Tbx19       98.2   │ ┌─ Mbre        ·
  HG1.6  Tbx2/Tbx3        47   33    88.1   Tbx2/Tbx3     88.1   │ ├─ Sros        ·
  HG1.12 like:Eomes/…     77   45     0.0 ⚠ like:…        12.0   │ │ ┌─ Mlei      ●2
```
- **Left — OG table** (`DataTable`, pane title `OGs`): one row per orthogroup, sorted by gene count
  descending: short OG id (`HG1.0`), name (the part after `:`), gene count, species count,
  `orthogroup_support`, `reference_ortholog`, `reference_support`. `orthogroup_support == 0` is
  shown as `0.0 ⚠` (the GeneRax / I93 bug-case marker; footer explains it).
- **Right — species tree** (`Static` in a scroll container, pane title `species tree`): the
  **binary** species tree `params.SPECIES_TREE` (`data/species_tree.binary.newick`, 59 tips; all
  gene-id prefixes in v3 map to a tip — checked 09/10/2026 on `tfs.T-box.HG1`), drawn with
  box-drawing characters, internal nodes labelled by their newick names (clades). For the
  highlighted OG each tip shows `●n` (n member genes of that species) or `·` (absent); each named
  clade shows `k/m spp` (species of the clade carrying ≥ 1 member). Redrawn on every OG cursor move.
- **`p`** toggles the source directory `possvm/` (post-GeneRax, default when it exists) ↔
  `possvm_prev/` (raw IQ-TREE). The title shows which one is shown. (House rule: read both.)
- Footer: `n OGs · source · ⚠ = support 0 (GeneRax bug case; check possvm_prev)`.

### Data (print-free, in `model.py`)
- `read_ogs(cfg, hg, source) -> list[OG] | None` — `OG(id, name, genes: list[str], support,
  ref, ref_support)`; reads `<outdir>/<source>/<hg>.*.ortholog_groups.csv` (tab-separated, header
  `gene orthogroup orthogroup_support reference_ortholog reference_support`; the orthogroup
  column is `<hg>.<n>:<name>`). `None` when no file (stage not done). Exactly one file per HG and
  source is expected; more than one is an error naming them.
- `species_of(gene) -> str` — the prefix before the first `_` (`Mlei_v05_G…` → `Mlei`).
- `og_coverage(og) -> dict[species, int]`.
- Tree parsing and drawing live in a new `phylocli/species_tree.py` (`load(path)`,
  `render(tree, counts) -> list[str]`), pure functions, no Textual. Uses `ete3` (already required
  by the stage scripts / preflight). Leaves in the tree but never in any OG are drawn as `·`;
  species in an OG but not in the tree are listed under the tree as `not in species tree: …`.

### Errors
- No POSSVM output for the HG/source: the screen opens with "no ortholog groups yet (`<stage>`
  not done)" and `p` still works.
- Unparseable CSV row: the screen shows the file and line, no crash.
- Reading happens in a worker thread (files are on NFS); the screen shows "loading…" until done.

### Testing
`test_model.py`: `read_ogs` on a fixture CSV (names, counts, support 0 flag, missing file → None,
two files → error); `species_of`. `test_species_tree.py`: render of a 4-tip fixture tree with
counts (tips `●n`/`·`, clade `k/m spp`), unknown species listed. `test_tui.py`: `o` opens
`OGScreen`, cursor move redraws the tree for the new OG, `p` switches source, `esc` returns with
the HG cursor kept; missing output message.

## Part B — overview sort and filter

Approved 09/10/2026. In pane `Overview`, both act on the **highlighted column**:
- **`s` sort**: rows by the highlighted stage's failed+ready count (descending), tie-break running
  count; `s` again reverses. On the `group` column: by name; on `HGs`: by size.
- **`h` hide**: toggles hiding every row with nothing to do at the highlighted stage (failed +
  ready + running = 0, i.e. done-only or blocked-only rows).
- `ALL` stays pinned on top; the title shows the state, e.g. `sort: tree ▼ · only actionable at tree`.
- Both survive refreshes and `c`/`f` regrouping (re-applied to the new rows), and are pure
  in-memory operations on `ov_rows` (no file or SLURM access on the key press).
- With step1 built, the same works on the `search`/`cluster` columns (counts in families).

Testing: sort order by a stage column and reversal; `h` hides done-only rows and keeps `ALL`;
state kept across `load_now()` and across `f`; no `core.ready_set` / subprocess on `s`/`h`
(patch to raise).

## Out of scope
possvm vs possvm_prev side by side, Mlei member annotation lines, pairs-file (`pairs_orthologs`)
views, mouse interaction.
