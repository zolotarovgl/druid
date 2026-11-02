# druid Results tab — clusters and orthogroups in one tab, source chosen per HG

Date: 02/11/2026 · Branch: `main` · Status: direction agreed in chat with Grygoriy ("one tab is a
better option"); this document awaits his review.

## Why
Measured on `/no_backup/asebe/gzolotarov/druid-try/test` (02/11/2026):
- The Results tab lists only HGs with an `ortholog_groups.csv`; HGs that are clustered (step 1
  done) but not through step 2 do not appear, so the clustering cannot be explored before trees.
- The source is chosen once per project (`model.default_source`, `druid/model.py:901`):
  `possvm/` as soon as that directory exists, else `possvm_prev/`. An HG with only a
  `possvm_prev` result is then shown as having nothing. Grygoriy: "if possvm_prev exists for a HG
  this should count as an available result".

## Goals
- Every clustered HG is listed in the Results tab, from the moment its cluster FASTA exists.
- Per HG, the best available result is shown: `possvm` (post-GeneRax) if present, else
  `possvm_prev` (raw IQ-TREE), else the cluster's members only.
- What each HG is showing is visible (a column), so nothing is mistaken for a final result.

## Non-goals
- A second tab (rejected: Grygoriy chose one tab).
- Any change to what step 1 / step 2 write; the tab only reads.
- The possvm display rename (TODOs, "for later").

## Design
- **Per-HG source ("auto", the default).** For each HG: `possvm` when
  `<outdir>/possvm/<hg>.*.ortholog_groups.csv` is non-empty, else `possvm_prev` likewise, else
  `cluster`. Each directory is still listed once per load (NFS), as `group_ogs` does now.
  `HGOgs` gains `source: str` (`"possvm" | "possvm_prev" | "cluster"`).
- **Source key** (the existing toggle): cycles `auto -> possvm -> possvm_prev -> auto`. A forced
  source shows only HGs that have it (today's behaviour); `auto` is the default and what the
  title shows as `source: auto`.
- **Cluster-only HGs.** Members are read from `<outdir>/clusters/<hg>.fasta` (gene ids from the
  `>` lines; species = `species_of(gene)`). In the OGs pane such an HG has one row,
  `(not split: no possvm yet)`, holding all members; members and species panes work as for an OG.
  No support, no reference name, no origin.
- **Which HGs are listed.** Every HG with a cluster FASTA, including those below `min_seqs` /
  `min_distinct` (they never reach step 2); those carry `too small for step 2` in the source
  column. (Claude's call: exploring the clustering means seeing all of it; reversible.)
- **Group rows (Results tab overview).** Per group: HGs, `with OGs` (possvm or possvm_prev),
  `cluster only`, OGs, genes, as now otherwise.
- **HG list column `source`**: `possvm`, `prev`, `cluster`, or `small`.

## Builder notes
- `model.default_source` stays for the forced modes; `group_ogs(cfg, hgs, source)` gains
  `source="auto"`, listing `possvm/`, `possvm_prev/` and `clusters/` once each.
- Origins (`og_origins`) are computed for OG rows only; cluster-only rows get none.
- The `_og_cache` key includes the source mode.
- Reading a cluster FASTA is one pass over `>` lines; no Biopython.

## Testing
Unit: `group_ogs(..., "auto")` picks possvm over possvm_prev per HG, falls back to cluster,
marks small HGs; a forced source keeps today's result. TUI: an HG with only `possvm_prev` is
listed with OGs while another HG has `possvm`; a cluster-only HG lists its members; the toggle
cycles the three modes; group-row counts.
