# druid — Counts heatmap in Results (design, 14/10/2026; refreshed for druid 11/11/2026)

Refresh (11/11/2026): written for phylocli before the rename; checked against druid `b83287f`.
Changes: module paths `druid/counts.py` + `druid/counts_tui.py` (`tui.py` is 2,645 lines);
HG members via `model.read_cluster_members`; Results tab = `#rtab`, Results window = view
`results`; quit is `:q!`, not `q`; tests in `tests/` with the local `python3` full suite; docs in
`docs/reference.md`; deploy = git push to the cluster clone. No T-box csv fixture exists in
`tests/data/`: `og_cols` is tested on a small hand-written POSSVM csv.

## Intent (Grygoriy)

Bring the step-2 HTML report's **Counts** tab into druid's TUI, reachable from the Results
section: a species × gene-group count heatmap with the species tree beside it, drilled down
class → family → HG → OG, from which a gene tree opens. Asked for on 13/10/2026; decisions made
in the brainstorm on 13–14/10/2026:

- **Full drill-down**: class → family → HG → OG (plus a Custom OG view).
- **Species are rows** (cladogram on the left, as in the HTML default); groups are **numbered
  columns** with a legend.
- **Counts come from the same files as the HTML**: family from `search/*.genes.list`, HG from
  `clusters/*.fasta`, OG from the POSSVM `ortholog_groups.csv`.
- Extras kept: z-score / absolute colouring, open the tree from a cell, collapse cladogram
  clades into summed rows, sort columns by a species, Custom OG list.

## Reference: what the HTML Counts tab does

`Phylogenies_v3/workflow/report_step2.py`, `drawHeatmap()` (line 7022 on 13/10/2026).

| level | columns | counts from | click |
|---|---|---|---|
| class | one per class (genefam column 7 = the id prefix, e.g. `tfs`) | sum of its families | → family |
| family | families of the class, total desc | `results/search/<class>.<family>.genes.list` (one gene id per line) | → HG |
| hg | HGs of the family, total desc | headers of `results/clusters/<class>.<family>.<HG>.fasta` | header → OG; cell → tree / alignment |
| og | OGs of the HG, total desc | the HG's `ortholog_groups.csv` | → tree / alignment |
| custom | OGs picked by search | as og | → tree / alignment |

Cell colour: z-score of the count within the column across the shown species (mean and
`d3.deviation`, i.e. sample SD, SD 0 → 1), `RdBu` diverging over [zmax, 0, −zmax] (high = red), or
absolute count on `Blues` from 0 to the matrix max. The count is printed in the cell (`≫` over 999),
text dark or light by background luminance (threshold 0.45). Also: species-tree cladogram aligned
with the rows, row-total bar, sort columns by a species' count, collapse a clade of the cladogram,
free-text column filter, drag reorder, row split bands, column grouping, PNG/SVG export.

**Not ported**: drag reorder, row split bands (shift+click), column grouping by HG/family/class,
the free-text column filter (the Custom search replaces it), PNG/SVG export, species logos,
alignment opening.

Note, kept as the HTML does it: family counts are search hits and HG counts are clustered
sequences, so a family's total need not equal the sum of its HGs.

## Data

New module **`druid/counts.py`**, pure (no Textual; file reads only in the loaders).

```python
@dataclass
class Col:
    id: str            # class "tfs" · family "tfs.T-box" · HG "tfs.T-box.HG1" · OG "tfs.T-box.HG1.0"
    label: str         # what the legend and status line show (OG: "HG1.0:T/Tbx19")
    counts: dict       # {species code: n}, n > 0 only
    @property
    def total(self) -> int
```

Species code of a gene: `model.species_of` (the gene id up to the first `_`). The HTML splits
on `_`, then on `.`; the two differ only for ids without `_` — druid's rule is kept so the
heatmap agrees with the rest of the TUI.

| function | reads | returns |
|---|---|---|
| `family_cols(cfg, fams) -> (list[Col], int)` | `cfg.outdir/search/<fam>.genes.list` for each `fam` in `fams` (blank and `#` lines skipped) | one Col per family with ≥ 1 gene; int = unreadable files |
| `hg_cols(cfg, hgs) -> (list[Col], int)` | `model.read_cluster_members(cfg, hg)` (headers of `cfg.outdir/clusters/<hg>.fasta`) | one Col per HG with ≥ 1 sequence; int = unreadable files |
| `class_cols(fam_cols) -> list[Col]` | — | sums of families by `id.split(".", 1)[0]` |
| `og_cols(hgogs) -> list[Col]` | — (an `model.HGOgs`) | one Col per OG, label `<HG part>.<n>:<name>` |
| `order_cols(cols, by=None) -> list[Col]` | — | `by=None`: total desc, then id; `by=set of species`: summed count of those species desc, ties in the default order |
| `zscores(matrix) -> list[list[float]]` | — | per column, over the rows given: `(v − mean) / sd`, sample SD, SD 0 or 1 row → 1 |
| `cell_colour(v, z, mode, zmax, vmax) -> (bg, fg)` | — | hex colours: `RdBu` at z / `Blues` at v; fg `#222222` / `#eeeeee` by luminance 0.45 |

`fams` = `core.family_ids(cfg)` when `genefam_info` is set, else every `*.genes.list` stem.
`hgs` = `core.expected(cfg)` (FASTAs of HGs that are not expected are not shown).
OG columns come from the Results tab's existing OG cache (`_og_cache`, current source); when the
cache does not hold the HG, `model.read_ogs` reads that one HG.

**Loading**: `family_cols` + `hg_cols` run once per session in a background worker (its own
worker group, like the Results-tab read), with the spinner showing `reading counts k/n`; about 3 s
cold on v3 (13/10/2026: 354 genes.list, 2,368 FASTAs). `R` in the screen re-reads.

## Species axis

Rows = the tips of `params.SPECIES_TREE` (`data/species_tree.binary.newick`, 59 tips) in tree
order. Checked 13/10/2026: every species in `tfs.T-box.HG1`'s POSSVM csv (56) is one of the 59.

The cladogram is the vendored treeview's **compact** cladogram (`layout.clado_rows(m, gap=-1)`
on a `TreeModel` of the species tree): one row per shown leaf, so a collapsed clade is one row and
its counts are the sum over its tips. Collapse state lives on that `TreeModel` and is kept across
levels for the life of the screen.

Extra rows, below the tree rows:
- `(not on tree)` — genes whose species is not a tip; shown only when non-zero; its status line
  lists the codes with counts. Not coloured, and not part of the z-scores.
- `Σ` — column totals (all genes, `(not on tree)` included). Not coloured.

A right-hand `total` column holds each row's total over the shown columns.

## Screen

**`CountsScreen`** (new, in `druid/counts_tui.py`), a full-screen `Screen` holding a `DataTable` (cell cursor) with the cladogram and the
species label as **fixed** columns, the numbered columns, then `total`; a one-line legend under it;
the app's status line as elsewhere. Border title = the breadcrumb: `Counts · tfs › tfs.T-box ›
HG1`.

- Column header = the column number (1-based), width = max(3, digits of the count of columns).
- Cell: the count right-aligned, `·` for 0, counts over 99 as `99+` (3-wide); background and
  foreground from `cell_colour`.
- Legend: from the cursor's column onward, `n label` entries, as many as fit one line; the
  cursor's entry bold.
- Status line on a cell: `<label> · <species or clade (k spp.)> · <count> genes · z <z>`.

### Opening (`H`)

| from | cursor on | opens at |
|---|---|---|
| Results tab (`#rtab`) | ALL | class level |
| Results tab | a category row | family level of that class |
| Results tab | a family row | HG level of that family |
| Results window (view `results`) | an HG (res pane) | OG level of that HG |
| Results window | an OG or a member | OG level of its HG, cursor on that OG's column |

`H` is added to the app bindings (shown on the Results tab and in the Results window) and to the
`overview_results` and `results` `?` tables.

### Keys (inside the screen)

| key | does |
|---|---|
| ↑ ↓ ← → pgup pgdn home end | move the cell cursor |
| enter | drill into the column: class → family → HG → OG; at OG / Custom: status `bottom level · t opens the tree` |
| esc | up one level; from the level it was opened at (or Custom's origin), close the screen |
| t | HG level: the whole gene tree, the cursor species' tips marked; OG / Custom: the OG's MRCA, members marked (same as Results' `t`); class / family: status `t: HG or OG level only`; no tree file: status `no tree for <hg>` |
| c | colour: z-score ↔ absolute (status `colour: z-score` / `colour: absolute`) |
| s | sort the columns by the cursor row's count (a collapsed clade: its sum); again on the same row: back to the default order. Reset on drill |
| z | collapse the clade above the cursor row (a tip → its parent; a collapsed clade → its parent); the root is never collapsed (status `whole tree`) |
| e | expand every collapsed clade |
| p | possvm ↔ possvm_prev (OG and Custom levels; elsewhere status `p: OG level only`) |
| / | search OGs by OG id/name, gene id or HG id (case-insensitive substring) over the OG cache; enter adds every hit to the Custom view and shows it; no OG cache yet: status `OGs still loading` and the Results-tab read is started |
| x | Custom only: drop the cursor's column |
| R | re-read the counts |
| ? | the key list (`KeysScreen`, table checked with `missing_keys`) |
| :q! | quit druid, as elsewhere |

## Errors

- An unreadable genes.list / FASTA is skipped; the status line says `N files unreadable`.
- A level with no columns shows one line `no data` (e.g. a family with no FASTA yet).
- Species tree unreadable (`OSError` / parse error): `H` does not open the screen; status
  `species tree unreadable: <error>`.
- An HG whose OG csv cannot be parsed (`HGOgs.error`): OG level shows `no data` and the status
  line carries the error.

## Tests

pytest, `tests/test_counts.py` (pure) and pilot tests in `tests/test_tui.py` style; the full suite
(`python3 -m pytest -q -p no:cacheprovider -rf`) must pass before each commit. A headless pilot smoke
test on v3 on login1 after deploy.

- `counts.py` on small fixture dirs: family / HG / class sums, unreadable files counted, empty
  files dropped, `fams` / `hgs` filters honoured.
- `og_cols` on a hand-written POSSVM csv fixture (3 OGs): labels and totals.
- `order_cols` default and by-species, ties stable; `zscores` against hand values, SD 0 → 1, a
  single row; `cell_colour` ends of both scales and the luminance switch.
- Collapse: a collapsed clade's row equals the sum of its tips; `(not on tree)` row shown only
  when non-zero; `Σ` equals the column totals.
- Pilot: `H` from each opener lands on the right level; enter / esc walk the levels and close at
  the origin; `c`, `s` twice, `z` twice then `e`, `p`, `/` + enter + `x`, `t` pushes a
  `TreeScreen`; `?` table has no `missing_keys`.

## Docs

`docs/reference.md`: the `H` key and the screen's keys. Deployed by git push to
`login1:projects/druid`.
