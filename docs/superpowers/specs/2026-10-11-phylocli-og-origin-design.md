# phylocli: orthogroup origin (Dollo MRCA) in the Results window — design

Date: 11/10/2026 · Branch: `phylocli` · Status: design approved in chat (Grygoriy, 11/10/2026),
spec awaiting review.
Builds on: `2026-10-09-phylocli-tui-og-explorer-sort-design.md` (Results window),
`2026-10-09-phylocli-tui-results-tab-header-sort-design.md` (header sorting, `/` per pane).

## Purpose

Grygoriy, 11/10/2026: show where each POSSVM orthogroup originates on the species tree, as a
column in the Results window ("1. this"), computed as "a simple dollo parsimony". The same
computation will later run inside step4 (analysis and interpretation of the orthogroups), so it
lives in one shared module now (approach C).

## Definition

- **Origin of an OG** = the most recent common ancestor (MRCA), on the origin tree, of every
  member species that is a tip of that tree. Under Dollo parsimony (single gain, losses only)
  this is the node of the gain. Strict: one member species in an outgroup moves the origin to
  the deeper node; no outlier trimming.
- Species code of a gene = `model.species_of` (text before the first `_`), as everywhere in
  phylocli.
- Member species that are not tips of the origin tree are ignored for the origin. An OG with no
  member on the tree has origin `–`.
- **Label**: the MRCA node's name. An unlabelled internal node shows as
  `~<nearest labelled ancestor>`; the unlabelled root shows as `root`.
- **Depth**: number of edges from the root to the MRCA (root = 0). A single-species OG has the
  tip itself as its origin (label = the species code, depth = its tip depth).

## Origin tree

- New config key `params.ORIGIN_TREE`, default `data/species_tree.newick` (Grygoriy, 11/10/2026:
  "use species_tree.newick"). This tree keeps polytomies, so no zero-length resolution nodes;
  `species_tree.binary.newick` resolves them into arbitrary unlabelled nodes.
- `params.SPECIES_TREE` (binary) is unchanged and still drives the species pane.
- Measured 11/10/2026 on v3: 59 tips; unlabelled internal nodes = the root,
  `(Pliv,(Spur,Lytvar))` and `(Spur,Lytvar)` (both shown as `~Eleutherozoa`); one 3-way
  polytomy example: `(Hvul,Hydrsy,Turdoh)Anthoathecata`.

## Components

1. **`workflow/og_origin.py`** — standard library only (no ete3, pandas or phylocli import), so
   step4 can import it unchanged.
   - `parse_newick(text) -> Node` — handles polytomies, branch lengths, internal labels with
     dots (`Scleractinia.2`, `Ctenophora.Mlei_Bol`), no trailing newline.
   - `class OriginTree(text)`: `tips` (set), `origin(species: Iterable[str]) -> Origin | None`
     where `Origin = (label: str, depth: int)`; `None` when no species is a tip. MRCA through
     parent pointers and depths, O(members × depth).
2. **`phylocli/model.py`**: `origin_tree(cfg) -> OriginTree` (reads `params.ORIGIN_TREE`,
   relative to the repo root as other params paths); `OG` gains `origin: Origin | None`, filled
   by `read_ogs` / `group_ogs` when a tree is passed (no tree → `None`; no second file read).
3. **`phylocli/tui.py`**: the Results window's species worker (which already reads the universe
   and phyla once) also reads the origin tree once and keeps it; OGs loaded afterwards carry the
   origin.
   - `OGs` pane: new column `origin` after `spp`.
   - `members` pane: new column `origin` (the gene's OG's origin).
   - Header sorting: `origin` sorts by depth, oldest (smallest depth) first, ties by label; again
     → reverse.
   - `/` filter in `OGs` and `members` also matches the origin label (substring,
     case-insensitive), e.g. `/Metazoa`.

## Error handling

- Origin tree missing or unparseable: the column shows `?` for every OG, one notification per
  session (`_notify_once`), and the rest of the window works as today.
- A member species not on the tree is not an error (it is already listed by `og_outside`).

## Testing

- `og_origin`: the real v3 tree copied as a test fixture → 59 tips, the three unlabelled nodes;
  origin of one species = that tip; of `Mbre`+`Sros` = `Choanoflagellata`; of `Hvul`+`Turdoh`
  (polytomy) = `Anthoathecata`; of `Spur`+`Pliv` = `~Eleutherozoa`; of `Mlei`+`Cowc` = `root`;
  of `Mlei`+`Hsap` = `Metazoa`; unknown species ignored; all unknown → `None`.
- `model`: `read_ogs` with a tree fills `origin`; without a tree leaves `None`.
- TUI (fixture tree): the `origin` column in `OGs` and `members`; header sort by depth; `/Metazoa`
  filters `OGs`; an unreadable tree gives `?` and one notification.
- `og_origin.py` imports nothing outside the standard library (asserted by a test).

## Out of scope

Writing origin tables (step4), per-HG / per-family aggregation of origins, PastML
(`workflow/ancestral_reconstruction.py`, currently not wired into `step4.ancestry.nf`), outlier
trimming, and the Results tab (first screen).
