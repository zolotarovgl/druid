# phylocli TUI: ortholog-group explorer + overview sort/filter — design

Date: 09/10/2026 · Branch: `phylocli` · Status: designs approved in chat (Grygoriy), spec awaiting review
Builds on: `2026-10-08-phylocli-tui-design.md` (overview, HG view, panes `Overview`, `1 Stages`,
`2 HGs`, `3 Arrays`, `4 Detail`).

## Part A — ortholog-group (OG) explorer: the **Results** window

(Amended 09/10/2026, Grygoriy: "drawing the trees is not important. It's important to implement a
backend to be able to select a HG or OG and explore interactively the annotation file and species
stats per OG." The species-tree drawing is dropped.)

### Goal
From an HG, open its POSSVM orthology result, step through its ortholog groups, and for the
selected OG browse its rows of the annotation file (`*.ortholog_groups.csv`) and its per-species /
per-phylum counts. Grygoriy chose: **call + support** and **species coverage**.

### Entry and exit — a third top-level window, **Results**
`o` on an overview row (any column; `ALL` allowed) opens Results for that group; `o` on an HG in
pane `2 HGs` opens Results for that HG's group (`group_key(hg, by)`) with that HG highlighted;
`o` on a family row (search/cluster stage) opens Results for that family's HGs. `esc` returns to
the window it was opened from (cursor kept). (`R` stays "refresh".)

### Layout — four panes, `tab` / `shift+tab` between them, focused pane in orange
```
┌ Results · tfs.T-box ─────┬ OGs · tfs.T-box.HG1 ──────────────┬ members · HG1.6 Tbx2/Tbx3 ─────────────┐
│ ▸ tfs.T-box.HG1  15 OGs  │ HG1.0  T/Tbx19     69 41  78.4    │ gene                 sp    ref.orth  sup│
│   tfs.T-box.HG2   3 OGs  │ ▸HG1.6 Tbx2/Tbx3   47 33  88.1    │ Mlei_v05_G005841     Mlei  Tbx2/Tbx3 88 │
│                          │ HG1.12 like:Eomes  77 45   0.0 ⚠  ├ species · HG1.6 ───────────────────────┤
│                          │                                    │ Ctenophora   3/5 spp  4 genes          │
│                          │                                    │   Mlei 2 · Bolinf 1 · Berova 1          │
```
- **Pane `Results`** — the group's HGs that have POSSVM output for the current source: HG, number of
  OGs, number of genes, number of OGs with support 0 (`⚠`). Sorted by HG id; HGs without output are
  not listed (the footer says how many). Moving here changes `OGs`.
- **Pane `OGs`** — one row per orthogroup of the highlighted HG, sorted by gene count descending:
  short OG id (`HG1.0`), name (the part after `:`), gene count, species count,
  `orthogroup_support` (no reference-ortholog columns: the reference is per gene — it differs
  within 1,671 of 8,996 possvm OGs, measured 09/10/2026 — so it is shown per row in `members`;
  Grygoriy, 09/10/2026). Support exactly `0` → `0.0 ⚠`
  (GeneRax / I93 bug case; footer explains); `-1` and other numbers shown as read; `NA` → `–`.
  Moving here changes `members` and `species`.
- **Pane `members`** — the annotation-file rows of the highlighted OG: gene, species (gene-id
  prefix), `reference_ortholog`, `reference_support`. `/` opens a filter box (substring on any
  column, e.g. `Mlei`); `esc` in the box clears it.
- **Pane `species`** — genes per species for the highlighted OG, grouped by phylum: one line per
  phylum `<phylum>  k/m spp  n genes` followed by its species with counts; phyla with no member are
  listed last as `absent: …`. The species universe (`m`) is the tips of `params.SPECIES_TREE`
  (the binary species tree, 59 species; only the tip NAMES are read — no tree drawing, no ete3);
  phylum from `data/species_info.tsv` (column 3; species missing there → `unknown`). Species in the
  OG but not in the universe are listed as `not in species tree: …`.
- **`p`** toggles the source directory `possvm/` (post-GeneRax, default when it exists) ↔
  `possvm_prev/` (raw IQ-TREE); the title shows which. (House rule: read both.)

### Data (print-free, in `model.py`)
- `read_ogs(cfg, hg, source) -> list[OG] | None` — `OG(id, name, genes: list[Member], support,
  ref, ref_support)`, `Member(gene, species, ref, ref_support)`; reads
  `<outdir>/<source>/<hg>.*.ortholog_groups.csv` (tab-separated, header `gene orthogroup
  orthogroup_support reference_ortholog reference_support`; orthogroup column `<hg>.<n>:<name>`).
  `None` when no non-empty file (stage not done). More than one file per HG and source → error
  naming them.
- `species_of(gene) -> str` — prefix before the first `_`.
- `species_universe(cfg) -> list[str]` (tip names of `params.SPECIES_TREE`, regex over the newick)
  and `phyla(cfg) -> dict[species, phylum]` (`data/species_info.tsv`), both cached per session.
- `og_species_stats(og, universe, phyla) -> list[PhylumRow]` — `PhylumRow(phylum, covered, total,
  n_genes, species: list[(sp, n)])`, phyla with members first (by n_genes desc), then absent ones.

### Errors
- No POSSVM output for the HG/source: the panes show "no ortholog groups yet (`<stage>` not done)";
  `p` still works.
- Unparseable CSV row: the pane shows the file and line, no crash.
- File reads happen in a worker thread (NFS); the panes show "loading…" until done.

### Testing
`test_model.py`: `read_ogs` on a fixture CSV (names, counts, support 0 / -1 / NA, missing file →
None, two files → error); `species_of`; `species_universe` from a fixture newick; `phyla`;
`og_species_stats` (covered/total per phylum, absent phyla, species outside the universe).
`test_tui.py`: `o` from the overview / an HG / a family row opens Results; moving in `Results`
changes `OGs`; moving in `OGs` changes `members` and `species`; `/` filters `members`; `p`
switches source; `esc` returns with the cursor kept; reads in a worker (patch to block → loading).

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
possvm vs possvm_prev side by side, GENE_ANNOTATION_v4 lines for members, pairs-file
(`pairs_orthologs`) views, species-tree drawing (dropped 09/10/2026), mouse interaction.
